"""合同管理压测（perf-loadtest-db-opt 方法论）：2000+ 合同 × 50 管理员。

用法：
  .venv\\Scripts\\python.exe scripts\\run_servers.py      # 另开
  .venv\\Scripts\\python.exe scripts\\load_contract_mgmt.py --seconds 20 --think 1.5

阶段：
  1) setup：seed 2000 合同（parties/inputs/效果）+ 20 公司 + 50 管理员账号（--seed-override 可调）
  2) load：50 线程并发拉 合同列表 / 合同详情 / 增量同步（TCP_NODELAY + 长连接 + 思考时间）
  3) 报告：稳态 P50/P95/P99 + 预热分列（测量自检：勿用 urllib 裸客户端）
"""

import argparse
import http.client
import json
import os
import socket
import statistics
import sys
import threading
import time
import urllib.parse

REPO = os.path.join(os.path.dirname(__file__), '..')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(REPO, 'BusinessCompetitionManagerWeb'))

TARGETS = {'list': 400, 'detail': 400, 'sync': 400}


# ================================================================ 数据准备

def setup(n_contracts: int, n_admins: int):
    import django

    django.setup()

    from django.contrib.auth import get_user_model

    from apps.common import context as ctx
    from apps.competition import provisioning
    from apps.competition.companies.models import Company
    from apps.competition.contracts.models import Contract, ContractFieldEffect
    from apps.global_.competitions import services as comp_services
    from apps.global_.competitions.models import Competition
    from apps.global_.memberships.models import CompetitionMembership
    from rest_framework_simplejwt.tokens import RefreshToken

    User = get_user_model()
    competition = Competition.objects.filter(name='contractload赛').first()
    if competition is None:
        competition = comp_services.create_competition(
            name='contractload赛', created_by=None, code='CLOAD')
    alias = provisioning.ensure_competition_db(competition.db_name)
    ctx.set_competition_context(competition.id, alias)

    tokens = []
    for i in range(n_admins):
        user, _ = User.objects.get_or_create(
            username=f'cload_admin{i + 1:03d}',
            defaults={'display_name': f'合同压测管理员{i + 1}', 'email': f'cload{i}@smoke.local'},
        )
        CompetitionMembership.objects.get_or_create(
            user=user, competition=competition,
            defaults={'identity': 'ADMIN', 'is_active': True,
                      'managed_companies': [i % 20 + 1]},
        )
        refresh = RefreshToken.for_user(user)
        refresh['tv'] = user.token_version
        tokens.append((user.id, str(refresh.access_token)))

    if not Company.objects.exists():
        Company.objects.bulk_create(
            [Company(name=f'压测公司{i:02d}', industry_key='manufacturer')
             for i in range(1, 21)])
    companies = list(Company.objects.order_by('id')[:20])

    if Contract.objects.count() < n_contracts:
        print(f'  seeding contracts -> {n_contracts} ...')
        import random

        rnd = random.Random(42)
        batch = []
        for i in range(Contract.objects.count(), n_contracts):
            buyer = companies[i % 20]
            seller = companies[(i + 7) % 20]
            batch.append(Contract(
                contract_type_key='purchase',
                plugin_version='1.0.0',
                name=f'压测合同{i:05d}',
                status=rnd.choice(['POSTED', 'POSTED', 'EXECUTED', 'PENDING_PARTY', 'MOD_APPLYING']),
                parties=[
                    {'role': 'buyer', 'companyId': buyer.id, 'companyName': buyer.name,
                     'confirmOrder': 0, 'confirmAt': '2026-10-01T00:00:00+00:00',
                     'confirmedBy': 'seed'},
                    {'role': 'seller', 'companyId': seller.id, 'companyName': seller.name,
                     'confirmOrder': 1, 'confirmAt': '2026-10-01T00:00:01+00:00',
                     'confirmedBy': 'seed'},
                ],
                inputs={'product': f'P{i % 50}', 'quantity': i % 90 + 10, 'unitPrice': 5},
                unified_number=f'PO-CLOAD-FY1-{i + 1:04d}',
                round_no=i % 3,
                fiscal_year_id=None,
                created_by=tokens[i % len(tokens)][0],
            ))
            if len(batch) >= 500:
                Contract.objects.bulk_create(batch)
                batch = []
        if batch:
            Contract.objects.bulk_create(batch)
        # 效果审计（每合同 3 条，模拟真实落账）
        effects = []
        for c in Contract.objects.all()[:n_contracts]:
            for k in range(3):
                effects.append(ContractFieldEffect(
                    contract=c, company_id=c.parties[0]['companyId'],
                    field_key='cash', op='SUB', value_raw=100 + k,
                    before_raw=100000, after_raw=99900 - k, round_no=c.round_no))
        while effects:
            ContractFieldEffect.objects.bulk_create(effects[:1000])
            effects = effects[1000:]

    print(f'  setup done: competition={competition.id}, contracts={Contract.objects.count()}, '
          f'admins={len(tokens)}')
    ctx.clear_request_context()
    return competition.id, tokens


# ================================================================ 压测执行

def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]


def worker(token, base_url, seconds, stats, barrier, warm, phase, think, cid):
    parsed = urllib.parse.urlparse(base_url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=30)
    conn.connect()
    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    headers = {'Authorization': f'Bearer {token}', 'Connection': 'keep-alive',
               'X-Device-Screen': '1920x1080'}

    def hit(name, path, cursor=None):
        bucket = stats if phase['timed'] else warm
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

    base = f'/api/competitions/{cid}/contracts'
    # 预热（页面加载：合同列表首屏 + 增量追平）
    page = hit('list', f'{base}?page=1&pageSize=50')
    cursor = ''
    detail_id = None
    if isinstance(page, dict) and page.get('items'):
        detail_id = page['items'][0]['id']
    elif isinstance(page, list) and page:
        detail_id = page[0]['id']
    d0 = hit('sync', f'{base}?updatedAfter=2020-01-01T00:00:00Z&limit=2000')
    if d0 and d0.get('serverTime'):
        cursor = d0['serverTime']

    barrier.wait()
    phase['timed'] = True
    end = time.time() + seconds
    seq = 0
    while time.time() < end:
        page = hit('list', f'{base}?page=1&pageSize=50')
        if isinstance(page, dict) and page.get('items') and seq % 3 == 0:
            detail_id = page['items'][seq % len(page['items'])]['id'] or detail_id
        if detail_id:
            hit('detail', f'{base}/{detail_id}')
        sync_path = (f'{base}?updatedAfter={urllib.parse.quote(cursor, safe="")}'
                     if cursor else f'{base}?updatedAfter=2020-01-01T00:00:00Z')
        delta = hit('sync', sync_path)
        if delta and delta.get('serverTime'):
            cursor = delta['serverTime']
        seq += 1
        if think:
            time.sleep(think)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contracts', type=int, default=2000)
    parser.add_argument('--users', type=int, default=50)
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--think', type=float, default=1.5)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    args = parser.parse_args()

    cid, tokens = setup(args.contracts, args.users)
    stats = {k: {'lat': [], 'errors': []} for k in TARGETS}
    warm = {k: {'lat': [], 'errors': []} for k in TARGETS}
    phase = {'timed': False}
    barrier = threading.Barrier(len(tokens))
    threads = [
        threading.Thread(target=worker, daemon=True,
                         args=(t, args.base_url, args.seconds, stats, barrier, warm, phase,
                               args.think, cid))
        for t in (_token for _uid, _token in tokens)
    ]
    print(f'  load: {len(threads)} 管理员 × {args.seconds}s（think={args.think}s）...')
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print(f'\n== 合同管理压测（{args.contracts} 合同 × {len(threads)} 管理员，稳态） ==')
    all_ok = True
    for key, data in stats.items():
        lat = data['lat']
        if not lat:
            print(f'  {key:7s} 无样本')
            continue
        p50, p95, p99 = percentile(lat, 50), percentile(lat, 95), percentile(lat, 99)
        ok = p95 <= TARGETS[key] and not data['errors']
        all_ok = all_ok and ok
        print(f'  {key:7s} n={len(lat):5d}  P50={p50:7.1f}ms  P95={p95:7.1f}ms  P99={p99:7.1f}ms  '
              f'max={max(lat):7.1f}ms  errors={len(data["errors"])}  '
              f'target P95<{TARGETS[key]}ms  {"PASS" if ok else "FAIL"}')
        if data['errors']:
            print(f'          样例错误: {data["errors"][:3]}')
    print('  -- 预热（首屏加载，一次性） --')
    for key, data in warm.items():
        lat = data['lat']
        if lat:
            print(f'  {key:7s} n={len(lat):5d}  P50={percentile(lat, 50):7.1f}ms  '
                  f'P95={percentile(lat, 95):7.1f}ms  max={max(lat):7.1f}ms')
    total = sum(len(v['lat']) for v in stats.values())
    print(f'稳态总请求: {total}  QPS≈{total / args.seconds:.1f}')
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
