"""性能基准：HTTP 延迟（keep-alive）+ 单请求 SQL 条数 + 查询计划。

用法：
    python scripts/perf/bench_endpoints.py --cid 61 --iterations 40

前置：scripts/run_servers.py 已启动（HTTP 8000）；数据集由 seed_perf_competition.py 生成。
"""

import argparse
import http.client
import json
import os
import socket
import sys
import time
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, 'BusinessCompetitionManagerWeb')
sys.path.insert(0, BACKEND)
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

import django  # noqa: E402

django.setup()

from django.db import connections  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

from apps.common import context as ctx  # noqa: E402
from apps.competition import provisioning  # noqa: E402
from apps.competition.contracts.models import Contract  # noqa: E402
from apps.global_.accounts.models import User  # noqa: E402
from apps.global_.competitions.models import Competition  # noqa: E402
from BusinessCompetitionManagerWeb.settings.databases import (  # noqa: E402
    register_competition_db,
)

HTTP = os.environ.get('PERF_HTTP', 'http://127.0.0.1:8000')


class KeepAliveClient:
    """HTTP/1.1 keep-alive 客户端（TCP_NODELAY，避免 Nagle 让每请求虚高几十毫秒）。"""

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
            body = resp.read()
        except (http.client.HTTPException, OSError):
            self.conn.close()
            self.conn = self._connect()
            self.conn.request('GET', path, headers=self.headers)
            resp = self.conn.getresponse()
            body = resp.read()
        return resp.status, body


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1))))
    return ordered[index]


def bench_http(paths, token, iterations, cid):
    client = KeepAliveClient(HTTP, {
        'Authorization': f'Bearer {token}',
        'X-Competition-Id': str(cid),
        'Connection': 'keep-alive',
    })
    for label, path in paths:
        for _ in range(5):
            client.get(path)
        samples = []
        errors = 0
        for _ in range(iterations):
            started = time.perf_counter()
            status, _body = client.get(path)
            samples.append((time.perf_counter() - started) * 1000)
            if status >= 400:
                errors += 1
        print(f'{label:<28} P50={percentile(samples, 50):>7.1f}ms  '
              f'P95={percentile(samples, 95):>7.1f}ms  '
              f'P99={percentile(samples, 99):>7.1f}ms  错误={errors}')


def bench_sql(cid, alias, user):
    from django.conf import settings

    if 'testserver' not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
    client = APIClient()
    client.force_authenticate(user)
    comp = Competition.objects.using('default').get(pk=cid)
    register_competition_db(comp.db_name)
    ctx.set_competition_context(cid, alias)

    posted = Contract.objects.filter(status='POSTED').order_by('id').first()
    paths = [
        ('合同列表(第1页50)', f'/api/competitions/{cid}/contracts?page=1&pageSize=50'),
        ('合同详情', f'/api/competitions/{cid}/contracts/{posted.pk}'),
        ('合同增量(全量)', f'/api/competitions/{cid}/contracts?updatedAfter=2020-01-01T00:00:00%2B00:00&limit=500'),
        ('公司列表', f'/api/competitions/{cid}/companies'),
        ('股票列表', f'/api/competitions/{cid}/stock/stocks?page=1&pageSize=50'),
        ('K线(200轮)', f'/api/competitions/{cid}/stock/stocks/S001/candles?fromRound=0&limit=200'),
        ('股票同步(快照)', f'/api/competitions/{cid}/stock/sync'),
    ]
    print('\n=== 单请求 SQL 条数与耗时（in-process） ===')
    for label, path in paths:
        with CaptureQueriesContext(connections[alias]) as captured:
            started = time.perf_counter()
            resp = client.get(path)
            elapsed = (time.perf_counter() - started) * 1000
        print(f'{label:<20} SQL={len(captured.captured_queries):>4}  '
              f'耗时={elapsed:>8.1f}ms  status={resp.status_code}')

    print('\n=== 参与方可见性查询（EXPLAIN ANALYZE） ===')
    with connections[alias].cursor() as cur:
        cur.execute(
            'EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) '
            'SELECT * FROM contracts_contract '
            'WHERE deleted_at IS NULL AND parties @> %s::jsonb '
            'ORDER BY updated_at DESC LIMIT 50',
            [json.dumps([{'companyId': 7}])])
        for line in cur.fetchall():
            print('  ', line[0])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cid', type=int, default=61)
    parser.add_argument('--iterations', type=int, default=40)
    args = parser.parse_args()

    comp = Competition.objects.using('default').get(pk=args.cid)
    alias = provisioning.ensure_competition_db(comp.db_name)
    ctx.set_competition_context(comp.pk, alias)
    user = User.objects.using('default').get(username='full_admin')
    token = str(RefreshToken.for_user(user).access_token)

    posted = Contract.objects.filter(status='POSTED').order_by('id').first()
    paths = [
        ('健康检查(基线)', '/api/health'),
        ('合同列表(第1页50)', f'/api/competitions/{args.cid}/contracts?page=1&pageSize=50'),
        ('合同列表(状态过滤)', f'/api/competitions/{args.cid}/contracts?status=POSTED&page=1&pageSize=50'),
        ('合同增量(全量)', f'/api/competitions/{args.cid}/contracts?updatedAfter=2020-01-01T00:00:00%2B00:00&limit=500'),
        ('合同详情', f'/api/competitions/{args.cid}/contracts/{posted.pk}'),
        ('公司列表', f'/api/competitions/{args.cid}/companies'),
        ('股票列表', f'/api/competitions/{args.cid}/stock/stocks?page=1&pageSize=50'),
        ('K线(200轮)', f'/api/competitions/{args.cid}/stock/stocks/S001/candles?fromRound=0&limit=200'),
        ('股票同步(快照)', f'/api/competitions/{args.cid}/stock/sync'),
    ]
    print(f'=== HTTP 基准（{args.iterations} 次/接口，keep-alive） ===')
    bench_http(paths, token, args.iterations, args.cid)
    bench_sql(args.cid, alias, user)
