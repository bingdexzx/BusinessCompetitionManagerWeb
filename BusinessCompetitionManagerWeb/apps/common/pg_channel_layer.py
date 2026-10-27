"""PostgreSQL 跨进程 Channel Layer（channels 后端，多进程/多核部署用）。

问题：channels 默认的 ``InMemoryChannelLayer`` 只在**单进程内**有效。
本项目 HTTP（waitress，可多进程）与 WS（daphne）分端口部署后，
``messages.services._push`` 里的 ``group_send`` 发出的消息**到不了 WS 进程**；
上多核多进程后问题只会更严重。用 Redis（channels_redis）能解，但要新增中间件。

本后端用 **PostgreSQL 做跨进程消息总线**（项目本来就必装 PG，零新增组件）：

- ``gipfel_channel_group``：group → channel 成员表（有过期时间）；
- ``gipfel_channel_message``：消息邮箱，**投递即删**（DELETE ... RETURNING 原子取走）；
- 每进程一条后台 drainer 线程：按 ``poll_interval``（默认 0.1s）批量拉取本进程
  持有的 channel 的消息，投递到各 channel 的 ``asyncio.Queue``（不阻塞事件循环）；
- 每实例一条单线程 DB 执行器线程：所有同步写入（send/group_* 等）都在它上面跑，
  复用同一条线程级 PG 连接，避免 asyncio.to_thread 每调用新建线程 → 连接泄漏。

特性与取舍：
- 推送延迟 ≤ ``poll_interval``；本项目「推送只当信号 + 客户端去抖 1.5s」的
  设计下完全够用。要更低延迟可把 ``poll_interval`` 调到 0.05 甚至更小；
- 消息体走 ``json`` 序列化（与前端协议一致，都是 JSON）；
- 进程内 ``capacity`` 在投递侧生效（队列满丢最旧一条）；跨进程未投递的孤儿
  消息由 ``expiry``（默认 60s）清扫，group 成员由 ``group_expiry``（默认 24h）清扫；
- 多进程/多机通用：只要连同一个 PostgreSQL，跨进程、跨机器都能收到。

配置见 settings/base.py：``CHANNEL_LAYER_BACKEND=postgres|memory|redis``。
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import threading
import time
import uuid
import weakref

from channels.layers import BaseChannelLayer

logger = logging.getLogger('gipfel.channel_layer')

# 本进程内创建过的 layer 实例（测试收尾/运维工具统一关闭长连接用）
_OPEN_LAYERS: "weakref.WeakSet" = weakref.WeakSet()


def close_open_layers(timeout: float = 2.0) -> None:
    """停掉 drainer 线程并关闭本 layer 打开的全部 PG 连接。

    主要给测试收尾用：测试库 ``DROP DATABASE`` 时若还有连接占用会失败
    （``database is being accessed by other users``）。
    """
    for layer in list(_OPEN_LAYERS):
        layer._shutdown(timeout=timeout)

# 连接参数里不能直接透传给 psycopg2.connect 的键
_PSYCOPG2_SKIP_OPTIONS = {
    'cursor_factory', 'context', 'async_', 'connection_factory', 'prepare_threshold',
}

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS gipfel_channel_message (
        id BIGSERIAL PRIMARY KEY,
        channel_name VARCHAR(100) NOT NULL,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    'CREATE INDEX IF NOT EXISTS gipfel_channel_message_channel_idx '
    'ON gipfel_channel_message (channel_name, id)',
    """
    CREATE TABLE IF NOT EXISTS gipfel_channel_group (
        group_name VARCHAR(100) NOT NULL,
        channel_name VARCHAR(100) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (group_name, channel_name)
    )
    """,
    'CREATE INDEX IF NOT EXISTS gipfel_channel_group_channel_idx '
    'ON gipfel_channel_group (channel_name)',
)

# 原子取走本进程持有的 channel 的消息（并发 drainer 之间用 SKIP LOCKED 互不干扰）
_DRAIN_SQL = """
    DELETE FROM gipfel_channel_message
    WHERE id IN (
        SELECT id FROM gipfel_channel_message
        WHERE channel_name = ANY(%s)
        ORDER BY id
        LIMIT %s
        FOR UPDATE SKIP LOCKED
    )
    RETURNING channel_name, payload
"""


class _ChannelState:
    """一个 channel 在本进程内的接收队列（绑定创建它的事件循环）。"""

    __slots__ = ('loop', 'queue')

    def __init__(self, loop, capacity: int):
        self.loop = loop
        self.queue = asyncio.Queue(maxsize=max(1, capacity))


class PostgresChannelLayer(BaseChannelLayer):
    """基于 PostgreSQL 的跨进程 channel layer（groups + flush 扩展）。"""

    extensions = ['groups', 'flush']

    def __init__(self, expiry=60, group_expiry=86400, capacity=100,
                 channel_capacity=None, poll_interval=0.1, **kwargs):
        super().__init__(
            expiry=expiry, capacity=capacity,
            channel_capacity=self.compile_capacities(channel_capacity or {}),
        )
        self.group_expiry = int(group_expiry)
        self.poll_interval = max(0.01, float(poll_interval))
        self._states: dict[str, _ChannelState] = {}
        self._states_lock = threading.Lock()
        self._tls = threading.local()
        self._conns: list = []
        self._conns_lock = threading.Lock()
        self._drainer = None
        self._drainer_lock = threading.Lock()
        # 所有同步 DB 写操作（send/group_* 等）都跑在这唯一一条后台线程上，
        # 从而复用该线程的线程级连接（self._tls），避免 asyncio.to_thread 每调用
        # 新建线程 → 每线程各开一条 PG 连接造成连接泄漏。
        self._executor = None
        self._executor_lock = threading.Lock()
        self._stop = threading.Event()
        _OPEN_LAYERS.add(self)

    # ------------------------------------------------------------ 连接

    def _connect(self):
        """新建一条 autocommit 连接（复用线程级连接；建表幂等）。"""
        import psycopg2
        from django.conf import settings

        cfg = settings.DATABASES['default']
        options = {
            k: v for k, v in (cfg.get('OPTIONS') or {}).items()
            if k not in _PSYCOPG2_SKIP_OPTIONS
        }
        conn = psycopg2.connect(
            dbname=cfg['NAME'],
            user=cfg.get('USER') or '',
            password=cfg.get('PASSWORD') or '',
            host=cfg.get('HOST') or 'localhost',
            port=cfg.get('PORT') or '5432',
            connect_timeout=int(options.pop('connect_timeout', 5)),
            **options,
        )
        conn.autocommit = True
        self._ensure_schema(conn)
        return conn

    @staticmethod
    def _ensure_schema(conn):
        """幂等建表；并发建表偶发冲突则重试一次。"""
        for attempt in (0, 1):
            try:
                with conn.cursor() as cur:
                    for stmt in _DDL:
                        cur.execute(stmt)
                return
            except Exception:  # noqa: BLE001 —— 另一进程正并发建表
                if attempt:
                    raise
                time.sleep(0.2)

    def _conn(self):
        """当前线程的连接（每个线程复用一条，避免每请求 ~44ms 建连开销）。"""
        conn = getattr(self._tls, 'conn', None)
        if conn is None or conn.closed:
            conn = self._connect()
            self._tls.conn = conn
            with self._conns_lock:
                self._conns.append(conn)
        return conn

    def _reconnect(self):
        conn = getattr(self._tls, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
        self._tls.conn = None

    def _shutdown(self, timeout: float = 2.0):
        """停 drainer + 停 DB 执行器 + 关闭本实例打开的全部连接。

        注意：本方法**不能**在 DB 执行器线程内调用（``close()`` 走 ``asyncio.to_thread``、
        ``close_open_layers`` 走调用方线程，二者都不是执行器线程），否则
        ``executor.shutdown(wait=True)`` 会等待自身造成死锁。
        """
        self._stop.set()
        thread = self._drainer
        if thread is not None:
            thread.join(timeout=timeout)
        # 先停执行器并排空其上的在途写操作，再关连接，避免关闭后执行器线程
        # 又因 conn.closed 重建连接导致泄漏。
        with self._executor_lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=True)
        with self._conns_lock:
            conns, self._conns = self._conns, []
        for conn in conns:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ channel 状态

    def _channel_state(self, channel: str) -> _ChannelState:
        loop = asyncio.get_running_loop()
        with self._states_lock:
            state = self._states.get(channel)
            if state is None:
                state = _ChannelState(loop, self.get_capacity(channel))
                self._states[channel] = state
            else:
                state.loop = loop
            return state

    def _local_channels(self) -> list:
        with self._states_lock:
            return list(self._states)

    # ------------------------------------------------------------ drainer

    def _ensure_drainer(self):
        thread = self._drainer
        if thread is not None and thread.is_alive():
            return
        with self._drainer_lock:
            thread = self._drainer
            if thread is None or not thread.is_alive():
                self._stop.clear()
                thread = threading.Thread(
                    target=self._drain_loop, name='pg-channel-layer-drainer', daemon=True)
                self._drainer = thread
                thread.start()

    def _ensure_executor(self) -> "ThreadPoolExecutor":
        """惰性创建单线程 DB 执行器（所有同步 DB 写操作都在这条线程上跑）。

        固定 ``max_workers=1``：所有 send/group_* 共享同一条后台线程，从而复用
        该线程的线程级连接（``_conn()``），不会每调用开一条新连接。
        """
        executor = self._executor
        if executor is not None:
            return executor
        with self._executor_lock:
            executor = self._executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix='pg-channel-db')
                self._executor = executor
            return executor

    async def _run_sync(self, func, *args):
        """在唯一后台 DB 线程上执行同步 ``func``：不阻塞事件循环、不新建线程。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._ensure_executor(), func, *args)

    def _drain_loop(self):
        last_sweep = 0.0
        while not self._stop.is_set():
            try:
                conn = self._conn()
                channels = self._local_channels()
                if channels:
                    with conn.cursor() as cur:
                        cur.execute(_DRAIN_SQL, (channels, 1000))
                        rows = cur.fetchall()
                    for channel, payload in rows:
                        self._deliver(channel, payload)
                now = time.time()
                if now - last_sweep > 60:  # 孤儿消息 / 过期成员清扫
                    last_sweep = now
                    self._sweep(conn)
            except Exception:  # noqa: BLE001 —— DB 抖动：重连继续，绝不打死 WS 进程
                logger.exception('channel layer 拉取失败，稍后重连')
                self._reconnect()
                self._stop.wait(1.0)
                continue
            self._stop.wait(self.poll_interval)

    def _deliver(self, channel: str, payload):
        state = self._states.get(channel)
        if state is None:  # 非本进程的 channel（或已不关心）
            return
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                logger.warning('channel layer 消息不是合法 JSON，丢弃')
                return

        def _put():
            queue = state.queue
            if queue.full():  # 超容量丢最旧（容量保护，见类文档）
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)

        try:
            state.loop.call_soon_threadsafe(_put)
        except RuntimeError:  # 事件循环已关闭
            pass

    def _sweep(self, conn):
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM gipfel_channel_message '
                'WHERE created_at < now() - make_interval(secs => %s)', (float(self.expiry),))
            cur.execute(
                'DELETE FROM gipfel_channel_group WHERE expires_at < now()', ())

    # ------------------------------------------------------------ 同步 DB 操作

    def _with_retry(self, func):
        """线程级连接上执行 ``func(cursor)``；连接失效时重建并重试一次。"""
        for attempt in (0, 1):
            try:
                conn = self._conn()
                with conn.cursor() as cur:
                    return func(cur)
            except Exception:  # noqa: BLE001
                self._reconnect()
                if attempt:
                    raise
        return None

    def _send_sync(self, channel: str, payload_json: str):
        self._with_retry(
            lambda cur: cur.execute(
                'INSERT INTO gipfel_channel_message (channel_name, payload) VALUES (%s, %s)',
                (channel, payload_json)))

    def _group_send_sync(self, group: str, payload_json: str):
        self._with_retry(
            lambda cur: cur.execute(
                'INSERT INTO gipfel_channel_message (channel_name, payload) '
                'SELECT channel_name, %s FROM gipfel_channel_group '
                'WHERE group_name = %s AND expires_at > now()',
                (payload_json, group)))

    def _group_add_sync(self, group: str, channel: str):
        self._with_retry(
            lambda cur: cur.execute(
                'INSERT INTO gipfel_channel_group (group_name, channel_name, expires_at) '
                'VALUES (%s, %s, now() + make_interval(secs => %s)) '
                'ON CONFLICT (group_name, channel_name) '
                'DO UPDATE SET expires_at = EXCLUDED.expires_at',
                (group, channel, float(self.group_expiry))))

    def _group_discard_sync(self, group: str, channel: str):
        self._with_retry(
            lambda cur: cur.execute(
                'DELETE FROM gipfel_channel_group WHERE group_name = %s AND channel_name = %s',
                (group, channel)))

    def _flush_sync(self):
        self._with_retry(
            lambda cur: cur.execute('DELETE FROM gipfel_channel_message'))
        self._with_retry(
            lambda cur: cur.execute('DELETE FROM gipfel_channel_group'))

    # ------------------------------------------------------------ channels API

    async def send(self, channel, message):
        assert isinstance(message, dict), 'message is not a dict'
        self.require_valid_channel_name(channel)
        self._ensure_drainer()
        # 注意：这里**不**注册到 _states——channel 的归属进程已通过
        # new_channel/group_add/receive 注册；发送方抢注会把消息拉到错误进程。
        await self._run_sync(self._send_sync, channel, json.dumps(message, default=str))

    async def receive(self, channel):
        """阻塞等待该 channel 的下一条消息（不阻塞事件循环）。"""
        self.require_valid_channel_name(channel)
        self._ensure_drainer()
        state = self._channel_state(channel)
        return await state.queue.get()

    async def new_channel(self, prefix='specific.'):
        """生成本进程专属 channel 名（唯一性保证消息只会被本进程拉走）。"""
        channel = f'{prefix}pg!{uuid.uuid4().hex[:12]}'
        self._channel_state(channel)
        self._ensure_drainer()
        return channel

    async def group_add(self, group, channel):
        self.require_valid_group_name(group)
        self.require_valid_channel_name(channel)
        self._channel_state(channel)
        self._ensure_drainer()
        await self._run_sync(self._group_add_sync, group, channel)

    async def group_discard(self, group, channel):
        self.require_valid_group_name(group)
        self.require_valid_channel_name(channel)
        await self._run_sync(self._group_discard_sync, group, channel)

    async def group_send(self, group, message):
        assert isinstance(message, dict), 'message is not a dict'
        self.require_valid_group_name(group)
        self._ensure_drainer()
        await self._run_sync(
            self._group_send_sync, group, json.dumps(message, default=str))

    async def flush(self):
        """清空全部消息与分组（测试用）。"""
        await self._run_sync(self._flush_sync)

    async def close(self):
        # close 是终态且低频（进程/测试收尾），保留 asyncio.to_thread 无妨：
        # _shutdown 不新建 PG 连接，也绝不在 DB 执行器线程内运行（见其注释）。
        await asyncio.to_thread(self._shutdown)
