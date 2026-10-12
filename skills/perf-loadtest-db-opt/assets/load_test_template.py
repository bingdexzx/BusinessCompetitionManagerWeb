"""通用压测脚本模板（perf-loadtest-db-opt skill 配套）。

用法：
  1. 修改 BASE_URL / ENDPOINTS / AUTH（登录取 token 的方式按项目调整）；
  2. 先起服务，再 `python load_test_template.py --users 60 --seconds 20 --think 1.5`；
  3. 读输出：分阶段（预热/稳态）P50/P95/P99 + 错误数 + QPS。

要点（缺一不可，否则测量失真）：
- TCP_NODELAY + 长连接（Nagle/延迟 ACK 会每请求虚增 ~80ms）；
- 预热（页面加载风暴）与稳态分开统计；
- --think 模拟前端去抖节奏；0 = 闭环轰炸（只用于找吞吐上限）。
"""

import argparse
import http.client
import json
import socket
import threading
import time
import urllib.parse

BASE_URL = 'http://127.0.0.1:8000'
# (统计名, 路径) —— 按项目改；带 {cursor} 的用 since 游标续拉
ENDPOINTS = [
    ('sync', '/api/things/sync?limit=500'),
    ('list', '/api/things?page=1&pageSize=50'),
]
AUTH_HEADER = {'Authorization': 'Bearer <token>'}  # 每线程替换为各自 token
TARGETS = {'sync': 400, 'list': 200}  # P95 目标（ms），按项目调整


def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]


def worker(token, seconds, stats, barrier, warm_stats, phase_ref, think):
    parsed = urllib.parse.urlparse(BASE_URL)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
    conn.connect()
    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    headers = {**AUTH_HEADER, 'Authorization': f'Bearer {token}', 'Connection': 'keep-alive'}

    def hit(name, path, cursor=None):
        bucket = stats if phase_ref['timed'] else warm_stats
        url = path
        if cursor:
            sep = '&' if '?' in path else '?'
            url = f'{path}{sep}since={urllib.parse.quote(cursor, safe="")}'
        t0 = time.perf_counter()
        try:
            conn.request('GET', url, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                bucket[name].setdefault('errors', []).append(f'status={resp.status}')
                return None
            return json.loads(body)
        except (OSError, http.client.HTTPException) as exc:
            bucket[name].setdefault('errors', []).append(str(exc)[:120])
            try:
                conn.close(); conn.connect()
                conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            return None
        finally:
            bucket[name].setdefault('lat', []).append((time.perf_counter() - t0) * 1000)

    # 预热：初始快照+续拉直到追平（不计时）
    cursor = ''
    for _ in range(40):
        page = hit(*ENDPOINTS[0], cursor or None)
        if page and page.get('serverTime'):
            cursor = page['serverTime']
        if not page or not page.get('hasMore'):
            break

    barrier.wait()
    phase_ref['timed'] = True
    end = time.time() + seconds
    while time.time() < end:
        page = hit(*ENDPOINTS[0], cursor or None)
        if page and page.get('serverTime'):
            cursor = page['serverTime']
        for name, path in ENDPOINTS[1:]:
            hit(name, path)
        if think:
            time.sleep(think)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--users', type=int, default=60)
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--think', type=float, default=1.5)
    parser.add_argument('--tokens', nargs='*', help='每用户一个 JWT；缺省用 AUTH_HEADER')
    args = parser.parse_args()
    tokens = args.tokens or [str(i) for i in range(args.users)]

    keys = [name for name, _ in ENDPOINTS]
    stats = {k: {'lat': [], 'errors': []} for k in keys}
    warm = {k: {'lat': [], 'errors': []} for k in keys}
    phase = {'timed': False}
    barrier = threading.Barrier(len(tokens))
    threads = [
        threading.Thread(target=worker, daemon=True,
                         args=(t, args.seconds, stats, barrier, warm, phase, args.think))
        for t in tokens
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f'\n== 稳态（{args.users} 并发 × {args.seconds}s，think={args.think}s） ==')
    for key in keys:
        lat = stats[key]['lat']
        if not lat:
            print(f'  {key:9s} 无样本')
            continue
        p50, p95, p99 = percentile(lat, 50), percentile(lat, 95), percentile(lat, 99)
        target = TARGETS.get(key, 400)
        ok = p95 <= target and not stats[key]['errors']
        print(f'  {key:9s} n={len(lat):5d}  P50={p50:7.1f}  P95={p95:7.1f}  P99={p99:7.1f}  '
              f'max={max(lat):7.1f}ms  errors={len(stats[key]["errors"])}  '
              f'target P95<{target}  {"PASS" if ok else "FAIL"}')
    print('  -- 预热（页面加载风暴，一次性） --')
    for key in keys:
        lat = warm[key]['lat']
        if lat:
            print(f'  {key:9s} n={len(lat):5d}  P50={percentile(lat, 50):7.1f}  '
                  f'P95={percentile(lat, 95):7.1f}  max={max(lat):7.1f}ms')
    total = sum(len(v['lat']) for v in stats.values())
    print(f'稳态总请求: {total}  QPS≈{total / args.seconds:.1f}')


if __name__ == '__main__':
    main()
