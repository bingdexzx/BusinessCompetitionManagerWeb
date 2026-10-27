"""吞吐压测（多核对照）：单接口并发压测，输出 QPS + P50/P95/P99 + 错误分布。

测量方法自检（重要，别让测量端骗了你）：
- **长连接 + TCP_NODELAY**：Python http.client 默认受 Nagle/延迟 ACK 影响，
  小包请求每请求可虚增 ~80ms（实测 curl 4ms vs urllib 80ms）；
- 本脚本复用同一连接发请求（keep-alive），并显式打开 TCP_NODELAY。

用法：
    .venv\\Scripts\\python.exe scripts\\load_throughput.py --users 32 --duration 15
    .venv\\Scripts\\python.exe scripts\\load_throughput.py --path /api/health --users 1 --duration 10

多核对照：
    python scripts\\run_servers.py --workers 1 --no-reload   → 压一轮（基线，单核）
    python scripts\\run_servers.py --workers 8 --no-reload   → 压一轮（多核）
"""

from __future__ import annotations

import argparse
import http.client
import socket
import statistics
import threading
import time


def _connect(host: str, port: int) -> http.client.HTTPConnection:
    conn = http.client.HTTPConnection(host, port, timeout=30)
    conn.connect()
    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return conn


def worker(host, port, path, headers, deadline, think, out: dict):
    latencies = []
    statuses: dict[int, int] = {}
    errors = 0
    try:
        conn = _connect(host, port)
    except OSError:
        out.update(latencies=[], statuses={}, errors=1)
        return
    while time.perf_counter() < deadline:
        t0 = time.perf_counter()
        try:
            conn.request('GET', path, headers=headers)
            resp = conn.getresponse()
            resp.read()
            latencies.append(time.perf_counter() - t0)
            statuses[resp.status] = statuses.get(resp.status, 0) + 1
        except Exception:  # noqa: BLE001 —— 连接断开/超时计为错误并重连
            errors += 1
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                conn = _connect(host, port)
            except OSError:
                break
        if think > 0:
            time.sleep(think)
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    out.update(latencies=latencies, statuses=statuses, errors=errors)


def pct(values, ratio):
    if not values:
        return 0.0
    idx = min(len(values) - 1, int(round(ratio * (len(values) - 1))))
    return values[idx]


def main():
    parser = argparse.ArgumentParser(description='多核吞吐压测客户端')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--path', default='/api/health')
    parser.add_argument('--users', type=int, default=32, help='并发虚拟用户数')
    parser.add_argument('--duration', type=float, default=15.0, help='计时窗（秒）')
    parser.add_argument('--think', type=float, default=0.0,
                        help='每请求后的思考时间（秒）；0=闭环压容量上限')
    parser.add_argument('--warmup', type=float, default=2.0, help='预热时间（秒），不计入统计')
    args = parser.parse_args()

    headers = {'Connection': 'keep-alive', 'Accept': 'application/json'}

    def run(window: float):
        results = [{} for _ in range(args.users)]
        deadline = time.perf_counter() + window
        threads = [
            threading.Thread(
                target=worker,
                args=(args.host, args.port, args.path, headers, deadline, args.think, results[i]),
                daemon=True)
            for i in range(args.users)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    if args.warmup > 0:
        run(args.warmup)  # 预热：连接池/缓存/JIT 类开销

    t0 = time.perf_counter()
    results = run(args.duration)
    elapsed = time.perf_counter() - t0

    latencies = sorted(x for r in results for x in r.get('latencies', []))
    statuses: dict[int, int] = {}
    errors = 0
    for r in results:
        for code, n in r.get('statuses', {}).items():
            statuses[code] = statuses.get(code, 0) + n
        errors += r.get('errors', 0)

    total = len(latencies) + errors
    print(f'目标        : {args.path}  (并发 {args.users}，{elapsed:.1f}s'
          f'{f"，思考 {args.think}s" if args.think else "，闭环"})')
    print(f'吞吐        : {len(latencies) / elapsed:.1f} QPS')
    if latencies:
        print(f'延迟(ms)    : P50={1000 * pct(latencies, 0.50):.1f}  '
              f'P95={1000 * pct(latencies, 0.95):.1f}  '
              f'P99={1000 * pct(latencies, 0.99):.1f}  '
              f'max={1000 * latencies[-1]:.1f}  '
              f'均值={1000 * statistics.fmean(latencies):.1f}')
    print(f'状态码      : {dict(sorted(statuses.items()))}')
    print(f'错误/重连   : {errors}（占 {100 * errors / total if total else 0:.2f}%）')
    return 0 if not errors and statuses and all(c < 500 for c in statuses) else 1


if __name__ == '__main__':
    raise SystemExit(main())
