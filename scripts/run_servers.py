"""一键启动（多核多进程）：HTTP（waitress WSGI，N 个 worker 共享监听套接字） + WebSocket（daphne ASGI）。

背景（压测实测，见 docs/数据库优化.md §1.0）：
- Django 同步视图在 ASGI（daphne）下按「线程敏感」单线程执行，32 并发仅 ~71 QPS；
  WSGI 多线程（waitress）同场景 ~910 QPS。故 **HTTP 与 WS 分端口部署**：
  - HTTP API：waitress，127.0.0.1:8000（--workers × --threads，见下）
  - WebSocket：daphne，127.0.0.1:8001（/ws/notifications 实时推送）
- **单进程 Python 受 GIL 限制，只能吃满一个 CPU 核**：吞吐天花板 ≈ 单核算力。
  本脚本默认按 CPU 核数拉起 N 个 HTTP worker，**共享同一个监听套接字**（prefork），
  内核把连接分发给不同进程 → 多核 CPU 直接换成吞吐；WS 为信号型推送（I/O 密集），
  单进程即可，不吃 CPU。

前端开发代理：vite `/api` → 8000、`/ws` → 8001（生产 nginx 同样分流）。

**代码热重载**：默认监控 *.py 变更自动重启（waitress/daphne 自身不热重载，
改后端代码不重启会一直跑旧逻辑）；生产部署加 --no-reload。

用法：
    .venv\\Scripts\\python.exe scripts\\run_servers.py                    # 全自动（worker 数 = CPU 核数）
    .venv\\Scripts\\python.exe scripts\\run_servers.py --workers 4 --threads 8
    .venv\\Scripts\\python.exe scripts\\run_servers.py --no-reload       # 生产

连接数预算（多库路由下每请求最多占 全局库+比赛库 两条连接）：
    max_connections >= workers × threads × 2 + 后台余量
    与 DB_MAX_CONCURRENT_REQUESTS（全局并发预算，见 settings）一起保证不打爆 PG。
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import socket
import subprocess
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(REPO, 'BusinessCompetitionManagerWeb')
SCRIPTS = os.path.join(REPO, 'scripts')
PYTHON = os.path.join(REPO, '.venv', 'Scripts', 'python.exe')
if not os.path.exists(PYTHON):  # 非 venv 布局（如 uv run / Linux 部署）时退回当前解释器
    PYTHON = sys.executable

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import server_workers  # noqa: E402  （worker 目标函数，须可被子进程 import）

WATCH_ROOTS = [BACKEND, SCRIPTS]
WATCH_EXT = ('.py',)


def snapshot() -> dict:
    """记录全部 .py 文件的 mtime（变更检测基线）。"""
    state = {}
    for root_dir in WATCH_ROOTS:
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            if '__pycache__' in dirpath or 'node_modules' in dirpath:
                continue
            for name in filenames:
                if name.endswith(WATCH_EXT):
                    path = os.path.join(dirpath, name)
                    try:
                        state[path] = os.path.getmtime(path)
                    except OSError:
                        pass
    return state


def build_http_listener(host: str, port: int) -> socket.socket:
    """创建并 ``listen()`` 监听套接字（只此一次；worker 只 accept）。

    Windows 实测：多个 worker 对同一共享套接字**并发 listen() 会竞态**
    （部分拿到 WSAEINVAL），故监听状态只由启动器置好。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


class Supervisor:
    """进程看护：HTTP prefork worker（multiprocessing）+ WS（daphne 子进程）。"""

    def __init__(self, args):
        self.args = args
        self.ctx = multiprocessing.get_context('spawn')
        self.listener = build_http_listener(args.host, args.http_port)
        self.env = dict(
            os.environ,
            DJANGO_SETTINGS_MODULE='BusinessCompetitionManagerWeb.settings',
            WEB_CONCURRENCY=str(args.workers),
        )
        self.http_workers = []
        self.ws_proc = None

    # ------------------------------------------------------------ 生命周期

    def start(self):
        self.http_workers = [
            self._spawn_http_worker(i) for i in range(self.args.workers)
        ]
        if not self.args.no_ws:
            self.ws_proc = subprocess.Popen(
                [PYTHON, '-m', 'daphne', '-b', self.args.host, '-p', str(self.args.ws_port),
                 'BusinessCompetitionManagerWeb.asgi:application'],
                cwd=BACKEND, env=self.env)

    def _spawn_http_worker(self, worker_id: int):
        proc = self.ctx.Process(
            target=server_workers.http_worker,
            args=(self.listener, self.args.threads, worker_id, dict(self.env)),
            name=f'http-worker-{worker_id}',
            daemon=True,
        )
        proc.start()
        return proc

    def stop(self):
        for proc in self.http_workers:
            if proc.is_alive():
                proc.terminate()
        for proc in self.http_workers:
            proc.join(timeout=5)
            if proc.is_alive():  # pragma: no cover —— 强杀兜底
                proc.kill()
        self.http_workers = []
        if self.ws_proc is not None and self.ws_proc.poll() is None:
            self.ws_proc.terminate()
            try:
                self.ws_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover
                self.ws_proc.kill()
            self.ws_proc = None

    def restart(self):
        self.stop()
        time.sleep(0.5)
        self.start()

    # ------------------------------------------------------------ 看护

    def check(self) -> list:
        """返回异常信息列表；顺手拉起挂掉的 worker（进程崩溃不拖垮整机）。"""
        problems = []
        for i, proc in enumerate(self.http_workers):
            if proc.exitcode is not None:
                problems.append(f'http-worker-{i} 退出（code={proc.exitcode}），自动重启')
                self.http_workers[i] = self._spawn_http_worker(i)
        if self.ws_proc is not None and self.ws_proc.poll() is not None:
            problems.append(f'ws(daphne) 退出（code={self.ws_proc.returncode}），自动重启')
            self.ws_proc = subprocess.Popen(
                [PYTHON, '-m', 'daphne', '-b', self.args.host, '-p', str(self.args.ws_port),
                 'BusinessCompetitionManagerWeb.asgi:application'],
                cwd=BACKEND, env=self.env)
        return problems


def db_connection_budget_check(workers: int, threads: int) -> None:
    """连接预算自检（压测实测教训）：**连接峰值 ≈ workers × threads × 2 + 后台**。

    多库路由下每线程最多同时持有 全局库 + 比赛库 2 条连接；`CONN_MAX_AGE=60`
    会让连接随线程滞留，故峰值按「线程总数 × 2」估算。超过 PostgreSQL
    `max_connections` 就是 `too many clients` 500 雪崩（压测已复现），这里提前拦住。
    """
    need = workers * threads * 2 + 20
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(REPO, '.env'))
        import psycopg2

        conn = psycopg2.connect(
            dbname=os.getenv('DATABASES_NAME', 'postgres'),
            user=os.getenv('DATABASES_USER', 'postgres'),
            password=os.getenv('DATABASES_PASSWORD', ''),
            host=os.getenv('DATABASES_HOST', 'localhost'),
            port=os.getenv('DATABASES_PORT', '5432'),
            connect_timeout=5,
        )
        try:
            with conn.cursor() as cur:
                cur.execute('SHOW max_connections')
                max_conn = int(cur.fetchone()[0])
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 —— 自检失败不影响启动
        print(f'（连接预算自检跳过：读不到 max_connections（{exc}））')
        return

    print(f'连接数预算: 需要 ≈ {need}（{workers} worker × {threads} 线程 × 2 + 余量 20）'
          f'/ PostgreSQL max_connections = {max_conn}')
    if need > max_conn:
        safe_threads = max(1, (max_conn - 20) // (2 * workers))
        print(f'[警告] 连接预算超限！超过 max_connections 会在压测/高峰触发 '
              f'`too many clients` 500 雪崩。')
        print(f'       建议 --workers {workers} --threads {safe_threads}，'
              f'或调高 PostgreSQL max_connections，或上 PgBouncer（transaction pooling）。')


def main():
    parser = argparse.ArgumentParser(description='HTTP(多进程 waitress) + WS(daphne) 一键启动')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--http-port', type=int, default=8000)
    parser.add_argument('--ws-port', type=int, default=8001)
    parser.add_argument('--workers', type=int, default=max(1, os.cpu_count() or 1),
                        help='HTTP worker 进程数（默认=CPU 核数；多核吞吐主要靠它）')
    parser.add_argument('--threads', type=int, default=None,
                        help='每个 worker 的线程数（默认自动：总线程≈32，见下）')
    parser.add_argument('--no-ws', action='store_true', help='不启动 WebSocket 服务')
    parser.add_argument('--reload', action=argparse.BooleanOptionalAction, default=True,
                        help='监控 *.py 变更自动重启（默认开启；生产部署用 --no-reload）')
    args = parser.parse_args()

    if args.workers < 1:
        parser.error('--workers 必须 >= 1')
    if args.threads is None:
        # 总线程数维持在 ~32：多核吞吐靠 worker 进程，线程只用来覆盖 I/O 等待，
        # 线程过多反而放大 DB 连接峰值（每线程最多 2 条连接）。
        args.threads = max(4, 32 // args.workers)

    total_threads = args.workers * args.threads
    db_connection_budget_check(args.workers, args.threads)  # 超预算先拦，再起服务
    sup = Supervisor(args)
    sup.start()

    print(f'HTTP  : http://{args.host}:{args.http_port}/api/  '
          f'({args.workers} 个 worker × {args.threads} 线程 = {total_threads} 并发槽，prefork 共享监听)')
    if not args.no_ws:
        print(f'WS    : ws://{args.host}:{args.ws_port}/ws/notifications  (daphne，1 进程)')
    print(f'热重载: {"开启（*.py 变更自动重启）" if args.reload else "关闭"}')
    print('Ctrl+C 停止。')

    baseline = snapshot() if args.reload else {}
    try:
        while True:
            time.sleep(2)
            for problem in sup.check():
                print(f'[看护] {problem}')
            if args.reload:
                current = snapshot()
                if current != baseline:
                    changed = [os.path.basename(p) for p in set(current) ^ set(baseline)
                               | {p for p in current if current.get(p) != baseline.get(p)}]
                    baseline = current
                    print(f'[热重载] 检测到代码变更（{", ".join(sorted(changed)[:5])}），重启服务...')
                    sup.restart()
    except KeyboardInterrupt:
        sup.stop()
        print('已停止。')


if __name__ == '__main__':
    main()
