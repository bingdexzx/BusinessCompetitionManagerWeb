"""一键启动：HTTP（waitress WSGI，多线程） + WebSocket（daphne ASGI）。

背景（压测实测）：Django 同步视图在 ASGI（daphne）下按「线程敏感」单线程执行，
并发 QPS 仅 ~70；WSGI 多线程（waitress）同场景 ~910 QPS。故 HTTP 与 WS 分端口部署：
- HTTP API：waitress，127.0.0.1:8000（--threads 可调，默认 32）
- WebSocket：daphne，127.0.0.1:8001（/ws/notifications 实时推送）
前端开发代理：vite `/api` → 8000、`/ws` → 8001（生产 nginx 同样分流）。

**代码热重载**：默认监控 *.py 变更自动重启两个服务（waitress/daphne 自身不热重载，
改后端代码不重启会一直跑旧逻辑）；生产部署加 --no-reload。

用法：.venv\\Scripts\\python.exe scripts\\run_servers.py [--http-port 8000] [--ws-port 8001] [--no-reload]
"""

import argparse
import os
import subprocess
import sys
import threading
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(REPO, 'BusinessCompetitionManagerWeb')
PYTHON = os.path.join(REPO, '.venv', 'Scripts', 'python.exe')
WATCH_ROOTS = [BACKEND]
WATCH_EXT = ('.py',)


def snapshot() -> dict:
    """记录全部 .py 文件的 mtime（变更检测基线）。"""
    state = {}
    for root_dir in WATCH_ROOTS:
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            if '__pycache__' in dirpath:
                continue
            for name in filenames:
                if name.endswith(WATCH_EXT):
                    path = os.path.join(dirpath, name)
                    try:
                        state[path] = os.path.getmtime(path)
                    except OSError:
                        pass
    return state


def start_servers(http_port: int, ws_port: int, threads: int):
    env = dict(os.environ, DJANGO_SETTINGS_MODULE='BusinessCompetitionManagerWeb.settings')
    procs = [
        ('http(waitress)', subprocess.Popen(
            [PYTHON, '-m', 'waitress', '--host=127.0.0.1', f'--port={http_port}',
             f'--threads={threads}', 'BusinessCompetitionManagerWeb.wsgi:application'],
            cwd=BACKEND, env=env)),
        ('ws(daphne)', subprocess.Popen(
            [PYTHON, '-m', 'daphne', '-b', '127.0.0.1', '-p', str(ws_port),
             'BusinessCompetitionManagerWeb.asgi:application'],
            cwd=BACKEND, env=env)),
    ]
    return procs


def stop_servers(procs):
    for _name, proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for _name, proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--http-port', type=int, default=8000)
    parser.add_argument('--ws-port', type=int, default=8001)
    parser.add_argument('--threads', type=int, default=32)
    parser.add_argument('--reload', action=argparse.BooleanOptionalAction, default=True,
                        help='监控 *.py 变更自动重启（默认开启；生产部署用 --no-reload）')
    args = parser.parse_args()

    procs = start_servers(args.http_port, args.ws_port, args.threads)
    print(f'HTTP  : http://127.0.0.1:{args.http_port}/api/  (waitress, threads={args.threads})')
    print(f'WS    : ws://127.0.0.1:{args.ws_port}/ws/notifications  (daphne)')
    print(f'热重载: {"开启（*.py 变更自动重启）" if args.reload else "关闭"}')
    print('Ctrl+C 停止。')

    baseline = snapshot() if args.reload else {}
    try:
        while True:
            time.sleep(2)
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f'{name} 退出（code={code}），停止全部服务。')
                    stop_servers(procs)
                    sys.exit(code or 1)
            if args.reload:
                current = snapshot()
                if current != baseline:
                    changed = [os.path.basename(p) for p in set(current) ^ set(baseline)
                               | {p for p in current if current.get(p) != baseline.get(p)}]
                    baseline = current
                    print(f'[热重载] 检测到代码变更（{", ".join(sorted(changed)[:5])}），重启服务...')
                    stop_servers(procs)
                    time.sleep(0.5)
                    procs = start_servers(args.http_port, args.ws_port, args.threads)
    except KeyboardInterrupt:
        stop_servers(procs)
        print('已停止。')


if __name__ == '__main__':
    main()
