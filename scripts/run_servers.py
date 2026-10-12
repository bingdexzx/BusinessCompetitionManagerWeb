"""一键启动：HTTP（waitress WSGI，多线程） + WebSocket（daphne ASGI）。

背景（压测实测）：Django 同步视图在 ASGI（daphne）下按「线程敏感」单线程执行，
并发 QPS 仅 ~70；WSGI 多线程（waitress）同场景 ~910 QPS。故 HTTP 与 WS 分端口部署：
- HTTP API：waitress，127.0.0.1:8000（--threads 可调，默认 32）
- WebSocket：daphne，127.0.0.1:8001（/ws/notifications 实时推送）
前端开发代理：vite `/api` → 8000、`/ws` → 8001（生产 nginx 同样分流）。

用法：.venv\\Scripts\\python.exe scripts\\run_servers.py [--http-port 8000] [--ws-port 8001]
"""

import argparse
import os
import subprocess
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BACKEND = os.path.join(REPO, 'BusinessCompetitionManagerWeb')
PYTHON = os.path.join(REPO, '.venv', 'Scripts', 'python.exe')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--http-port', type=int, default=8000)
    parser.add_argument('--ws-port', type=int, default=8001)
    parser.add_argument('--threads', type=int, default=32)
    args = parser.parse_args()

    env = dict(os.environ, DJANGO_SETTINGS_MODULE='BusinessCompetitionManagerWeb.settings')
    procs = [
        ('http(waitress)', subprocess.Popen(
            [PYTHON, '-m', 'waitress', f'--host=127.0.0.1', f'--port={args.http_port}',
             f'--threads={args.threads}', 'BusinessCompetitionManagerWeb.wsgi:application'],
            cwd=BACKEND, env=env)),
        ('ws(daphne)', subprocess.Popen(
            [PYTHON, '-m', 'daphne', '-b', '127.0.0.1', '-p', str(args.ws_port),
             'BusinessCompetitionManagerWeb.asgi:application'],
            cwd=BACKEND, env=env)),
    ]
    print(f'HTTP  : http://127.0.0.1:{args.http_port}/api/  (waitress, threads={args.threads})')
    print(f'WS    : ws://127.0.0.1:{args.ws_port}/ws/notifications  (daphne)')
    print('Ctrl+C 停止。')
    try:
        while True:
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f'{name} 退出（code={code}），停止全部服务。')
                    for _, other in procs:
                        if other.poll() is None:
                            other.terminate()
                    sys.exit(code or 1)
            time.sleep(1)
    except KeyboardInterrupt:
        for _, proc in procs:
            proc.terminate()
        print('已停止。')


if __name__ == '__main__':
    main()
