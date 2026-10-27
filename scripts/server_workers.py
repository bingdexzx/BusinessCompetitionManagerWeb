"""多进程 worker 进程入口（prefork 共享监听套接字，吃满多核 CPU）。

由 ``scripts/run_servers.py`` 用 ``multiprocessing``（spawn 上下文）拉起：

- 父进程 ``bind() + listen()`` 一次监听套接字，把它随 ``Process`` 参数传给 N 个 worker
  （``multiprocessing.reduction`` 会把套接字复制进子进程，Windows/Linux 通用）；
  **listen 只由父进程做一次**——Windows 上多进程对同一共享套接字并发 ``listen()``
  会竞态（实测 WSAEINVAL），worker 只按 ``SO_ACCEPTCONN`` 判定是否已监听（见
  ``_ensure_listening``）；
- 每个 worker 用 waitress 官方的 ``Adjustments(sockets=[...])``（systemd socket
  activation 同款机制）在**同一个套接字**上 ``accept()``，内核把新连接分发给
  不同进程 → HTTP 后端可以真正用满多核（单进程受 GIL 限制只能吃一个核）；
- 无需代理层、无需额外转发跳数，连接建立与业务处理都在 worker 内完成。

本模块**只在 worker 进程内**使用；顶层不导入 Django，保证启动器轻量、
子进程按需初始化。
"""

from __future__ import annotations

import os
import socket
import sys
import time

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(BACKEND_DIR, 'BusinessCompetitionManagerWeb')


def _bootstrap_django(env: dict | None = None) -> None:
    """在 worker 进程里初始化 Django 环境（必须先于任何 Django 导入）。"""
    if env:
        os.environ.update(env)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
    if BACKEND_DIR not in sys.path:
        sys.path.insert(0, BACKEND_DIR)
    # 与 run_servers 一致：从后端根目录跑，管理命令/相对路径行为才一致。
    try:
        os.chdir(BACKEND_DIR)
    except OSError:  # pragma: no cover —— 目录异常时保持原 cwd 继续
        pass


def _ensure_listening(sock, backlog: int, attempts: int = 50) -> None:
    """确保共享监听套接字处于 listen 状态（幂等，跨 worker 安全）。

    背景（Windows 实测）：同一个监听套接字被复制进多个 worker 进程后，
    **并发调用 ``listen()`` 会竞态**——部分进程拿到 WSAEINVAL，谁先谁成。
    因此由启动器只 ``listen()`` 一次，worker 先用 ``SO_ACCEPTCONN`` 判定：
    已监听就直接用；否则才补一次 ``listen()``，失败时稍候重试。
    """
    def _is_listening() -> bool:
        try:
            return bool(sock.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))
        except OSError:  # pragma: no cover —— 套接字异常时交由上层报错
            return False

    if _is_listening():
        return
    for attempt in range(attempts):
        try:
            sock.listen(backlog)
            return
        except OSError:
            if _is_listening():  # 其它 worker 抢先把它置为监听
                return
            if attempt == attempts - 1:
                raise
            time.sleep(0.1)


def http_worker(sock, threads: int = 8, worker_id: int = 0, env: dict | None = None) -> None:
    """单个 HTTP worker：在共享监听套接字上跑 waitress（WSGI 多线程）。

    参数
    ----
    sock:
        父进程已 ``bind() + listen()`` 的监听套接字（各 worker 在其上 ``accept()``）。
    threads:
        本 worker 的处理线程数（I/O 等待用；CPU 密集吞吐靠 worker 数量堆核）。
    worker_id:
        仅用于日志区分。
    env:
        附加环境变量（如 ``WEB_CONCURRENCY``、``DJANGO_SETTINGS_MODULE``）。
    """
    _bootstrap_django(env)

    from django.core.wsgi import get_wsgi_application
    from waitress import create_server

    application = get_wsgi_application()
    # _start=False：listen/accepting 由本函数统一处理（避开多 worker 并发 listen 竞态）
    server = create_server(
        application,
        sockets=[sock],
        threads=max(1, int(threads)),
        # 连接清理间隔：多 worker 下每个进程都做一次，调大减少空转
        cleanup_interval=30,
        _start=False,
    )
    _ensure_listening(sock, server.adj.backlog)
    server.accepting = True

    host, port = sock.getsockname()[:2]
    print(
        f'[http-worker-{worker_id}] pid={os.getpid()} 已就绪 '
        f'（共享监听 {host}:{port}，threads={threads}）',
        flush=True,
    )
    try:
        server.run()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover —— 交互式停止
        pass
    finally:
        try:
            server.close()
        except Exception:  # noqa: BLE001 —— 关闭失败不影响退出
            pass
