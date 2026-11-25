"""并发吞吐基准（真实节奏）：N 个虚拟用户 × 思考时间，混合接口。

用法：
    python scripts/perf/bench_concurrency.py --cid 61 --users 32 --seconds 30 --think 0.2

输出：每接口 P50/P95/P99、总 QPS、错误数。用于验证 400 人规模下的容量余量。
"""

import argparse
import http.client
import os
import socket
import sys
import threading
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, 'BusinessCompetitionManagerWeb')
sys.path.insert(0, BACKEND)
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

import django  # noqa: E402

django.setup()

from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from apps.competition import provisioning  # noqa: E402
from apps.global_.accounts.models import User  # noqa: E402
from apps.global_.competitions.models import Competition  # noqa: E402
from apps.competition.contracts.models import Contract  # noqa: E402

HTTP = os.environ.get('PERF_HTTP', 'http://127.0.0.1:8000')


class Client:
    def __init__(self, base_url, headers):
        parsed = urlparse(base_url)
        self.host = parsed.hostname or '127.0.0.1'
        self.port = parsed.port or 80
        self.headers = headers
        self.conn = None

    def _connect(self):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=60)
        conn.connect()
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return conn

    def get(self, path):
        if self.conn is None:
            self.conn = self._connect()
        try:
            self.conn.request('GET', path, headers=self.headers)
            resp = self.conn.getresponse()
            resp.read()
        except (http.client.HTTPException, OSError):
            self.conn.close()
            self.conn = self._connect()
            self.conn.request('GET', path, headers=self.headers)
            resp = self.conn.getresponse()
            resp.read()
        return resp.status


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cid', type=int, default=61)
    parser.add_argument('--users', type=int, default=32)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--think', type=float, default=0.2)
    args = parser.parse_args()

    comp = Competition.objects.using('default').get(pk=args.cid)
    provisioning.ensure_competition_db(comp.db_name)
    user = User.objects.using('default').get(username='full_admin')
    token = str(RefreshToken.for_user(user).access_token)
    headers = {
        'Authorization': f'Bearer {token}',
        'X-Competition-Id': str(args.cid),
        'Connection': 'keep-alive',
    }

    from apps.common import context as ctx
    ctx.set_competition_context(comp.pk, comp.db_name)
    posted = Contract.objects.filter(status='POSTED').order_by('id').first()

    paths = [
        ('合同列表', f'/api/competitions/{args.cid}/contracts?page=1&pageSize=50'),
        ('增量同步', f'/api/competitions/{args.cid}/contracts?updatedAfter=2026-01-01T00:00:00%2B00:00'),
        ('股票同步', f'/api/competitions/{args.cid}/stock/sync'),
        ('合同详情', f'/api/competitions/{args.cid}/contracts/{posted.pk}'),
    ]

    latencies = {label: [] for label, _ in paths}
    errors = {label: 0 for label, _ in paths}
    lock = threading.Lock()
    stop_at = time.time() + args.seconds

    def worker(index):
        client = Client(HTTP, headers)
        cursor = index
        while time.time() < stop_at:
            label, path = paths[cursor % len(paths)]
            cursor += 1
            started = time.perf_counter()
            try:
                status = client.get(path)
            except Exception:  # noqa: BLE001
                status = 599
            elapsed = (time.perf_counter() - started) * 1000
            with lock:
                latencies[label].append(elapsed)
                if status >= 400:
                    errors[label] += 1
            time.sleep(args.think)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.users)]
    started_at = time.time()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed_total = time.time() - started_at

    total_requests = sum(len(v) for v in latencies.values())
    total_errors = sum(errors.values())
    print(f'并发 {args.users} 用户 × {elapsed_total:.1f}s，思考时间 {args.think}s')
    print(f'总请求 {total_requests}，错误 {total_errors}，QPS {total_requests / elapsed_total:.1f}')
    for label, _ in paths:
        samples = latencies[label]
        if not samples:
            continue
        print(f'  {label:<8} n={len(samples):>5}  '
              f'P50={percentile(samples, 50):>7.1f}ms  '
              f'P95={percentile(samples, 95):>7.1f}ms  '
              f'P99={percentile(samples, 99):>7.1f}ms  错误={errors[label]}')


if __name__ == '__main__':
    main()
