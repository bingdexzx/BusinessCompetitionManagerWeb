"""网络日志异步批量写入。

请求线程只做 ``Queue.put_nowait``，后台线程按 100 条或 200ms 批量 ``bulk_create``：
- 避免每个请求同步写全局库、拖垮业务线程；
- 队列满时丢弃并计数（审计降级），不阻塞请求；
- 进程退出时尽量 flush；进程被强杀时队列内日志可能丢失，这是可用性取舍。
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

QUEUE_MAX = 50_000
BATCH_MAX = 100
BATCH_WINDOW = 0.2
SHUTDOWN_TIMEOUT = 3.0
FLUSH_RETRIES = 3

_queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)
_lock = threading.Lock()
_thread: threading.Thread | None = None
_dropped = 0


def _write_sync(item: dict) -> bool:
    """队列满/批量失败时的兜底：同步写一条，尽量不丢。"""
    from apps.global_.logs.models import NetworkLog

    try:
        NetworkLog.objects.using('default').create(**item)
        return True
    except Exception:  # noqa: BLE001
        logger.exception('网络日志同步兜底写入失败')
        return False


def _flush(batch: list[dict]) -> None:
    if not batch:
        return
    from apps.global_.logs.models import NetworkLog

    for attempt in range(1, FLUSH_RETRIES + 1):
        try:
            NetworkLog.objects.using('default').bulk_create(
                [NetworkLog(**item) for item in batch])
            return
        except Exception:  # noqa: BLE001 —— 日志失败不影响业务
            if attempt == FLUSH_RETRIES:
                logger.exception('网络日志批量写入失败（重试 %s 次），本批 %s 条',
                                 FLUSH_RETRIES, len(batch))
                for item in batch:
                    _write_sync(item)
            else:
                time.sleep(0.2 * attempt)


def _close_db() -> None:
    try:
        from django.db import connections

        connections.close_all()
    except Exception:  # noqa: BLE001 —— 解释器退出阶段忽略
        pass


def _run() -> None:
    batch: list[dict] = []
    while True:
        try:
            item = _queue.get(timeout=1.0)
        except queue.Empty:
            _flush(batch)
            batch = []
            continue
        if item is None:
            _flush(batch)
            _close_db()
            return
        batch.append(item)
        deadline = time.monotonic() + BATCH_WINDOW
        while len(batch) < BATCH_MAX:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                nxt = _queue.get(timeout=remaining)
            except queue.Empty:
                break
            if nxt is None:
                _flush(batch)
                _close_db()
                return
            batch.append(nxt)
        _flush(batch)
        batch = []


def _ensure_thread() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_run, name='network-log-buffer', daemon=True)
        _thread.start()


def enqueue_network_log(payload: dict) -> None:
    global _dropped
    _ensure_thread()
    try:
        _queue.put_nowait(payload)
        return
    except queue.Full:
        pass
    # 不直接丢弃：短暂等待后台消费；仍满则同步兜底，优先保证日志完整。
    try:
        _queue.put(payload, timeout=0.5)
    except queue.Full:
        _dropped += 1
        if _dropped == 1 or _dropped % 100 == 0:
            logger.warning('网络日志队列持续满，已同步兜底 %s 条', _dropped)
        _write_sync(payload)


def flush_network_logs(timeout: float = SHUTDOWN_TIMEOUT) -> None:
    if _thread is None or not _thread.is_alive():
        return
    _queue.put(None)
    _thread.join(timeout=timeout)


atexit.register(flush_network_logs)
