"""分层归因探针（perf-loadtest-db-opt skill 配套）。

子命令：
  connect-cost  [次数]        裸建连计时 vs 复用查询计时（判断连接复用收益）
  concurrency  [线程数] [秒]  无 DB 端点并发探针（判定 WSGI/ASGI 服务管线是否串行）
  breakdown                   逐接口单发计时（无并发固定开销归因）

环境变量：PROBE_BASE（默认 http://127.0.0.1:8000）、PROBE_TOKEN、PROBE_PATHS（逗号分隔）。
"""

import http.client
import os
import socket
import statistics
import sys
import threading
import time
import urllib.parse


def connect_cost(rounds=10):
    import psycopg2
    url = os.environ.get('PROBE_DB_DSN', '')
    kw = {}
    if url:
        kw = dict(item.split('=', 1) for item in url.split(' ') if '=' in item)
    else:
        kw = dict(dbname=os.environ.get('PROBE_DB_NAME', 'postgres'),
                  user=os.environ.get('PROBE_DB_USER', 'postgres'),
                  password=os.environ.get('PROBE_DB_PASSWORD', ''),
                  host=os.environ.get('PROBE_DB_HOST', '127.0.0.1'),
                  port=os.environ.get('PROBE_DB_PORT', '5432'))
    times = []
    for _ in range(rounds):
        t0 = time.perf_counter()
        conn = psycopg2.connect(**kw)
        times.append((time.perf_counter() - t0) * 1000)
        conn.close()
    print(f'新建连接: P50={statistics.median(times):.1f}ms min={min(times):.1f}ms '
          f'max={max(times):.1f}ms  → 结论：新建 <5ms 才可不复用，否则必须 CONN_MAX_AGE 复用')
    conn = psycopg2.connect(**kw)
    cur = conn.cursor()
    q = []
    for _ in range(50):
        t0 = time.perf_counter()
        cur.execute('SELECT 1')
        cur.fetchone()
        q.append((time.perf_counter() - t0) * 1000)
    print(f'复用查询: P50={statistics.median(q):.2f}ms')
    conn.close()


def concurrency(threads_n=32, seconds=8):
    base = urllib.parse.urlparse(os.environ.get('PROBE_BASE', 'http://127.0.0.1:8000'))
    path = os.environ.get('PROBE_HEALTH_PATH', '/api/health')
    counts = [0] * threads_n
    lats = []

    def loop(i):
        conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=30)
        conn.connect()
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        end = time.time() + seconds
        while time.time() < end:
            t0 = time.perf_counter()
            try:
                conn.request('GET', path, headers={'Connection': 'keep-alive'})
                resp = conn.getresponse()
                resp.read()
                lats.append((time.perf_counter() - t0) * 1000)
                counts[i] += 1
            except Exception:  # noqa: BLE001
                try:
                    conn.close(); conn.connect()
                    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                except OSError:
                    return

    threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(threads_n)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = sum(counts)
    lats.sort()
    print(f'并发={threads_n} QPS={total / (time.time() - t0):.1f} '
          f'P50={lats[len(lats) // 2]:.1f}ms P95={lats[int(len(lats) * 0.95)]:.1f}ms')
    print('→ 同一无DB端点：WSGI 与 ASGI 各测一遍，差距 >5× 说明 ASGI 单线程敏感执行是瓶颈')


def breakdown():
    base = urllib.parse.urlparse(os.environ.get('PROBE_BASE', 'http://127.0.0.1:8000'))
    token = os.environ.get('PROBE_TOKEN', '')
    paths = os.environ.get('PROBE_PATHS', '/api/health').split(',')
    for path in paths:
        times = []
        for _ in range(8):
            conn = http.client.HTTPConnection(base.hostname, base.port or 80, timeout=30)
            conn.connect()
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            headers = {'Connection': 'keep-alive'}
            if token:
                headers['Authorization'] = f'Bearer {token}'
            t0 = time.perf_counter()
            conn.request('GET', path.strip(), headers=headers)
            resp = conn.getresponse()
            resp.read()
            times.append((time.perf_counter() - t0) * 1000)
            conn.close()
        print(f'{path.strip():48s} P50={statistics.median(times):7.1f}ms '
              f'min={min(times):7.1f}ms  → 含 ~80ms/请求 说明测量端或建连有问题')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'breakdown'
    if cmd == 'connect-cost':
        connect_cost(int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    elif cmd == 'concurrency':
        concurrency(int(sys.argv[2]) if len(sys.argv) > 2 else 32,
                    int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    else:
        breakdown()


if __name__ == '__main__':
    main()
