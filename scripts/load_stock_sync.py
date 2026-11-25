"""股票同步压测（契约 §6）：模拟 60 个并发账号拉取 /stock/sync 增量与行情分页。

用法（先起后端）：
  .venv\\Scripts\\python.exe BusinessCompetitionManagerWeb\\manage.py runserver 127.0.0.1:8000
  .venv\\Scripts\\python.exe scripts\\load_stock_sync.py --seconds 20

阶段：
  1) setup：建 loadtest 比赛 + 60 账号 + 800 股票 × 30 轮 K 线 + 持仓/委托（--skip-setup 复用）
  2) load：60 线程各自持 JWT 并发拉 sync/stocks/book，记录 P50/P95/P99
  3) 报告：对照目标（delta P95 < 200ms、snapshot P95 < 800ms）

仅用标准库（threading/urllib），不给项目增加依赖。
"""

import argparse
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.parse

REPO = os.path.join(os.path.dirname(__file__), '..')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(REPO, 'BusinessCompetitionManagerWeb'))


# ================================================================ 数据准备

def setup(loadtest_users: int):
    """建比赛与压测数据，返回 (competition_id, [(user_id, token), ...])。"""
    import django

    django.setup()

    from django.contrib.auth import get_user_model

    from apps.common import context as ctx
    from apps.competition import provisioning
    from apps.competition.stock.models import (
        Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder,
    )
    from apps.global_.competitions import services as comp_services
    from apps.global_.competitions.models import Competition
    from apps.global_.memberships.models import CompetitionMembership
    from rest_framework_simplejwt.tokens import RefreshToken

    User = get_user_model()
    competition = Competition.objects.filter(name='loadtest赛').first()
    if competition is None:
        competition = comp_services.create_competition(
            name='loadtest赛', created_by=None, code='LOAD')
    alias = provisioning.ensure_competition_db(competition.db_name)
    ctx.set_competition_context(competition.id, alias)

    tokens = []
    for i in range(loadtest_users):
        user, _ = User.objects.get_or_create(
            username=f'load_u{i + 1:03d}',
            defaults={'display_name': f'压测用户{i + 1}', 'email': f'load{i}@smoke.local'},
        )
        CompetitionMembership.objects.get_or_create(
            user=user, competition=competition,
            defaults={'identity': 'PLAYER', 'is_active': True},
        )
        refresh = RefreshToken.for_user(user)
        refresh['tv'] = user.token_version
        tokens.append((user.id, str(refresh.access_token)))

    if not Stock.objects.exists():
        print('  seeding stocks/candles/accounts ...')
        stocks = [Stock(code=f'LOAD{i:04d}', name=f'压测股票{i}', total_shares=10 ** 6,
                        init_net_profit=10 ** 5, industry_pe=10.0, current_carbon=1.0,
                        industry_avg_carbon=1.0, happiness=50.0,
                        init_price=10, current_price=10, round=30)
                  for i in range(800)]
        Stock.objects.bulk_create(stocks, batch_size=500)
        stocks = list(Stock.objects.all())
        candles = []
        for s in stocks:
            for r in range(1, 31):
                candles.append(StockCandle(stock=s, round=r, open=10, high=10.2, low=9.8,
                                           close=10.1, change_pct=0.1, volume=1000))
        StockCandle.objects.bulk_create(candles, batch_size=2000)

        accounts, holdings, orders = [], [], []
        for idx, (uid, _t) in enumerate(tokens):
            acc = StockFundsAccount(name=f'load_acc{idx:03d}', owner_type='USER',
                                    user_id=uid, cash_balance=10 ** 7)
            accounts.append(acc)
        StockFundsAccount.objects.bulk_create(accounts, batch_size=200)
        accounts = list(StockFundsAccount.objects.all())
        for acc in accounts:
            for s in stocks[:20]:
                holdings.append(StockHolding(funds_account=acc, stock=s, shares=100, cost_price=10))
                orders.append(StockOrder(stock=s, funds_account=acc, side='BUY', price=10,
                                         quantity=10, amount=100, status='PENDING', round=30))
        StockHolding.objects.bulk_create(holdings, batch_size=200)
        StockOrder.objects.bulk_create(orders, batch_size=200)
    print(f'  setup done: competition={competition.id}, users={len(tokens)}')
    ctx.clear_request_context()
    return competition.id, tokens


# ================================================================ 压测执行

def percentile(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]


def worker(name, token, base_url, seconds, stats, barrier, cid, warm_stats, phase_ref,
           think=0.0):
    """单账号循环：sync(delta) 为主，穿插 sync(snapshot) / stocks / book。

    HTTP 客户端注意：必须设 TCP_NODELAY 并复用长连接——否则小包受 Nagle/延迟 ACK
    影响每请求虚增 ~80ms（实测 curl 4ms vs urllib 80ms），测量本身失真。
    """
    parsed = urllib.parse.urlparse(base_url)
    host, port = parsed.hostname or '127.0.0.1', parsed.port or 80
    conn = http.client.HTTPConnection(host, port, timeout=30)
    conn.connect()
    conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    headers = {'Authorization': f'Bearer {token}', 'X-Device-Screen': '1920x1080',
               'Connection': 'keep-alive'}

    def hit(endpoint, path, cursor=None):
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
                bucket[endpoint].setdefault('errors', []).append(f'status={resp.status}')
                return None
            return json.loads(body)
        except (OSError, http.client.HTTPException) as exc:
            bucket[endpoint].setdefault('errors', []).append(str(exc)[:120])
            try:  # 断线重连（长连接被服务端关闭时）
                conn.close()
                conn.connect()
                conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            return None
        finally:
            bucket[endpoint].setdefault('lat', []).append((time.perf_counter() - t0) * 1000)

    # ---- 预热（不计时）：模拟页面加载的初始快照+续拉，直到追平或 40 轮 ----
    base = f'/api/competitions/{cid}/stock'
    cursor = ''
    for _ in range(40):
        page = hit('sync', f'{base}/sync?limit=2000', cursor or None)
        if page and page.get('serverTime'):
            cursor = page['serverTime']
        if not page or not page.get('hasMore'):
            break

    barrier.wait()   # 全员追平后开始计时窗（测稳态增量，贴近比赛中持续同步）
    phase_ref['timed'] = True
    end = time.time() + seconds
    seq = 0
    while time.time() < end:
        page = hit('sync', f'{base}/sync?limit=500', cursor or None)
        if page and page.get('serverTime'):
            cursor = page['serverTime']   # 游标取服务端时间（热路径=delta）
        seq += 1
        if seq % 5 == 0:
            hit('stocks', f'{base}/stocks?page=1&pageSize=50')
        if seq % 7 == 0:
            hit('book', f'{base}/book')
        if seq % 20 == 0:
            hit('snapshot', f'{base}/sync?limit=500')  # 全量回归
        if think:  # 模拟前端去抖节奏（真实用户不是闭环轰炸）
            time.sleep(think)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--users', type=int, default=60)
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--think', type=float, default=1.5,
                        help='每轮循环后的思考时间（秒），模拟前端去抖节奏；0=闭环轰炸')
    parser.add_argument('--skip-setup', action='store_true')
    args = parser.parse_args()

    if not args.skip_setup:
        print('  setup ...')
    cid, tokens = setup(args.users)  # 幂等：已有 loadtest 数据则跳过 bulk

    stats = {}
    warm_stats = {}
    for key in ('sync', 'snapshot', 'stocks', 'book'):
        stats[key] = {'lat': [], 'errors': []}
        warm_stats[key] = {'lat': [], 'errors': []}
    phase_ref = {'timed': False}

    barrier = threading.Barrier(len(tokens))
    threads = [
        threading.Thread(target=worker, daemon=True,
                         args=(f'w{i}', token, args.base_url, args.seconds, stats, barrier, cid,
                               warm_stats, phase_ref, args.think))
        for i, (_uid, token) in enumerate(tokens)
    ]
    print(f'  load: {len(threads)} 并发账号 × {args.seconds}s ...')
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print('\n== 压测结果（计时窗=稳态增量） ==')
    print(f'并发账号: {len(threads)}  计时窗: {args.seconds}s')
    targets = {'sync': 200, 'snapshot': 800, 'stocks': 200, 'book': 200}
    all_ok = True
    for key, data in stats.items():
        lat = data['lat']
        errs = data['errors']
        if not lat:
            print(f'  {key:9s} 无样本')
            continue
        p50, p95, p99 = (percentile(lat, 50), percentile(lat, 95), percentile(lat, 99))
        ok = p95 <= targets[key] and not errs
        all_ok = all_ok and ok
        print(f'  {key:9s} n={len(lat):5d}  P50={p50:7.1f}ms  P95={p95:7.1f}ms  '
              f'P99={p99:7.1f}ms  max={max(lat):7.1f}ms  errors={len(errs)}  '
              f'target P95<{targets[key]}ms  {"PASS" if ok else "FAIL"}')
        if errs:
            print(f'            样例错误: {errs[:3]}')
    print('  -- 预热（页面加载初始快照+续拉，一次性） --')
    for key, data in warm_stats.items():
        lat = data['lat']
        if lat:
            print(f'  {key:9s} n={len(lat):5d}  P50={percentile(lat, 50):7.1f}ms  '
                  f'P95={percentile(lat, 95):7.1f}ms  max={max(lat):7.1f}ms  errors={len(data["errors"])}')
    total_req = sum(len(v['lat']) for v in stats.values())
    print(f'计时窗总请求: {total_req}  QPS≈{total_req / args.seconds:.1f}')
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
