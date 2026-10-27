"""PostgreSQL 跨进程 Channel Layer（channels 后端，多进程/多核部署用）。

channels 默认的 ``InMemoryChannelLayer`` 只在单进程内有效：HTTP（waitress）与 WS（daphne）
分端口部署后 ``group_send`` 到不了 WS 进程。项目本就必装 PG，故用 PG 做消息总线（零新增
组件）：``gipfel_channel_group`` 成员表 + ``gipfel_channel_message`` 邮箱（投递即删）。

改动前必读：每进程一条 drainer 线程按 ``poll_interval``（0.1s）拉取投递，延迟 ≤ 该值；每实例
一条单线程 DB 执行器复用线程级连接——否则 ``asyncio.to_thread`` 每次新建线程 → 每线程一条
PG 连接 → 连接泄漏。孤儿消息按 ``expiry``（60s）、成员按 ``group_expiry``（24h）清扫。"""

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

# 本进程创建过的 layer 实例（测试收尾统一关闭长连接用）
_OPEN_LAYERS: "weakref.WeakSet" = weakref.WeakSet()


def close_open_layers(timeout: float = 2.0) -> None:
    """停 drainer 并关闭全部 PG 连接（测试收尾必用：占用连接会让 ``DROP DATABASE`` 失败）。"""
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
        # 所有同步 DB 写操作都跑在这唯一一条后台线程上，以复用其线程级连接；
        # 否则 asyncio.to_thread 每调用新建线程 → 每条新连接 → 连接泄漏。
        self._executor = None
        self._executor_lock = threading.Lock()
        self._stop = threading.Event()
        _OPEN_LAYERS.add(self)

    def _connect(self):
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
        """当前线程的连接（每线程复用一条，避免每请求 ~44ms 建连开销）。"""
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
        """停 drainer + 停 DB 执行器 + 关闭全部连接。

        绝不能在 DB 执行器线程内调用：``executor.shutdown(wait=True)`` 会等自己 → 死锁。"""
        self._stop.set()
        thread = self._drainer
        if thread is not None:
            thread.join(timeout=timeout)
        # 先停执行器排空在途写操作，再关连接：否则执行器线程会因 conn.closed 重建连接造成泄漏。
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
        """惰性创建单线程 DB 执行器；固定 ``max_workers=1`` 才能复用同一条连接。"""
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
        if state is None:  # 非本进程的 channel
            return
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                logger.warning('channel layer 消息不是合法 JSON，丢弃')
                return

        def _put():
            queue = state.queue
            if queue.full():  # 超容量丢最旧
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

    async def send(self, channel, message):
        assert isinstance(message, dict), 'message is not a dict'
        self.require_valid_channel_name(channel)
        self._ensure_drainer()
        # 注意：**不**注册到 _states——channel 归属已由 new_channel/group_add/receive 注册，
        # 发送方抢注会把消息拉到错误进程。
        await self._run_sync(self._send_sync, channel, json.dumps(message, default=str))

    async def receive(self, channel):
        self.require_valid_channel_name(channel)
        self._ensure_drainer()
        state = self._channel_state(channel)
        return await state.queue.get()

    async def new_channel(self, prefix='specific.'):
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
        await self._run_sync(self._flush_sync)

    async def close(self):
        # 终态且低频，走 asyncio.to_thread 无妨：_shutdown 不新建连接，也不在执行器线程内跑。
        await asyncio.to_thread(self._shutdown)
