"""性能压测数据集：独立比赛库（不碰业务数据）。

用法：
    python scripts/perf/seed_perf_competition.py --rebuild
    python scripts/perf/seed_perf_competition.py --companies 400 --contracts 2000 \
        --stocks 30 --rounds 200

默认规模按「后期峰值」：400 家公司、2000+ 合同、30 支股票 × 200 轮 K 线。
脚本会创建/复用比赛 ``PERFDB``（库名 comp_perfdb），并给 full_admin 建管理员成员关系。
"""

import argparse
import os
import random
import sys
from datetime import timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, 'BusinessCompetitionManagerWeb')
sys.path.insert(0, BACKEND)
os.environ.setdefault(
    'DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

import django  # noqa: E402

django.setup()

from django.db import connections, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.common import context as ctx  # noqa: E402
from apps.global_.accounts.models import User  # noqa: E402
from apps.global_.competitions.models import Competition  # noqa: E402
from apps.global_.memberships.models import CompetitionMembership  # noqa: E402
from apps.competition import provisioning  # noqa: E402
from apps.competition.companies.models import Company  # noqa: E402
from apps.competition.contracts.models import Contract  # noqa: E402
from apps.competition.stock.models import Stock, StockCandle  # noqa: E402

COMP_CODE = 'PERFDB'
DB_NAME = 'comp_perfdb'


def ensure_competition() -> Competition:
    comp, created = Competition.objects.using('default').get_or_create(
        code=COMP_CODE,
        defaults={'name': '性能压测赛', 'db_name': DB_NAME},
    )
    if created:
        print(f'创建比赛 id={comp.pk}')
    return comp


def truncate(alias):
    tables = [
        'contracts_contractconfirmation', 'contracts_contractcheck',
        'contracts_contractfieldeffect', 'contracts_contractmodrequest',
        'ledger_contractfreeze', 'contracts_contract',
        'stock_candles', 'stock_holdings', 'stock_orders',
        'stock_funds_accounts', 'stocks',
        'industries_companyfieldvalue', 'fieldlogs_fieldlog',
        'companies_company',
    ]
    with connections[alias].cursor() as cur:
        cur.execute(
            'TRUNCATE TABLE ' + ', '.join(f'"{t}"' for t in tables) + ' RESTART IDENTITY CASCADE')


def seed(companies: int, contracts: int, stocks: int, rounds: int, rebuild: bool):
    comp = ensure_competition()
    provisioning.create_competition_database(comp.db_name)   # 建库 + 迁移（幂等）
    alias = provisioning.ensure_competition_db(comp.db_name)
    ctx.set_competition_context(comp.pk, alias)

    if rebuild:
        truncate(alias)

    user = User.objects.using('default').get(username='full_admin')
    CompetitionMembership.objects.using('default').get_or_create(
        competition=comp, user=user,
        defaults={'identity': CompetitionMembership.Identity.ADMIN},
    )

    now = timezone.now()
    with transaction.atomic(using=alias):
        existing_companies = Company.objects.count()
        if existing_companies < companies:
            Company.objects.bulk_create(
                [Company(name=f'压测公司{i:04d}', industry_key='industry1')
                 for i in range(existing_companies, companies)],
                batch_size=500,
            )
        company_ids = list(Company.objects.order_by('id').values_list('id', flat=True))
        print('公司数:', len(company_ids))

        existing_contracts = Contract.objects.count()
        todo = max(0, contracts - existing_contracts)
        if todo:
            statuses = (['POSTED'] * 8 + ['PENDING_PARTY'] + ['DRAFT'])
            batch = []
            for i in range(todo):
                idx = existing_contracts + i
                buyer = company_ids[idx % len(company_ids)]
                seller = company_ids[(idx * 7 + 3) % len(company_ids)]
                batch.append(Contract(
                    contract_type_key='perf_type',
                    name=f'压测合同{idx:05d}',
                    status=statuses[idx % len(statuses)],
                    parties=[
                        {'role': '买方', 'companyId': buyer},
                        {'role': '卖方', 'companyId': seller},
                    ],
                    inputs={'数量': idx % 50 + 1, '备注': f'压测数据 {idx}'},
                    unified_number=f'PERF-{idx:05d}',
                    round_no=0,
                    created_by=user.pk,
                    created_at=now - timedelta(days=idx % 60),
                ))
                if len(batch) >= 500:
                    Contract.objects.bulk_create(batch, batch_size=500)
                    batch = []
            if batch:
                Contract.objects.bulk_create(batch, batch_size=500)

            # updated_at 打散（bulk_create 会被 auto_now 覆盖成同一时刻）
            with connections[alias].cursor() as cur:
                cur.execute(
                    "UPDATE contracts_contract "
                    "SET updated_at = now() - (id % 2880) * interval '1 minute'")

        contract_count = Contract.objects.count()
        print('合同数:', contract_count)

        existing_stocks = Stock.objects.count()
        if existing_stocks < stocks:
            from decimal import Decimal
            Stock.objects.bulk_create(
                [Stock(code=f'S{(i + 1):03d}', name=f'压测股票{i + 1:03d}',
                       total_shares=Decimal('1000000.0000'),
                       init_net_profit=Decimal('50000.0000'),
                       industry_pe=12.5, current_carbon=10.0,
                       industry_avg_carbon=12.0, happiness=50.0,
                       init_price=Decimal('100.0000'),
                       current_price=Decimal('100.0000'))
                 for i in range(existing_stocks, stocks)],
                batch_size=200,
            )
        stock_rows = list(Stock.objects.order_by('id')[:stocks])
        print('股票数:', len(stock_rows))

        existing_candles = StockCandle.objects.count()
        need = stocks * rounds - existing_candles
        if need > 0:
            candles = []
            for stock in stock_rows:
                for r in range(existing_candles // max(len(stock_rows), 1), rounds):
                    price = 100 + (r % 50) * 0.6 + (stock.id % 7)
                    candles.append(StockCandle(
                        stock=stock, round=r + 1,
                        open=price, high=price * 1.01, low=price * 0.99,
                        close=price * 1.002, volume=1000 + r * 3,
                        change_pct=0.2,
                    ))
            StockCandle.objects.bulk_create(candles, batch_size=1000)
        print('K 线行数:', StockCandle.objects.count())

    print(f'\n压测比赛 cid = {comp.pk}（库 {comp.db_name}）')
    return comp.pk


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--companies', type=int, default=400)
    parser.add_argument('--contracts', type=int, default=2000)
    parser.add_argument('--stocks', type=int, default=30)
    parser.add_argument('--rounds', type=int, default=200)
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    random.seed(42)
    seed(args.companies, args.contracts, args.stocks, args.rounds, args.rebuild)
