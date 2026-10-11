"""M2–M5 端到端冒烟：组队/激活码 → 合同状态机 → 修改流程 → 财年/补录 → 结算/奖牌。

运行：.venv\\Scripts\\python.exe scripts\\smoke_full.py
（会真实写开发库与比赛库；用 scripts\\cleanup_smoke.py 清理冒烟残留）
"""

import json
import os
import sys
import tempfile

from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.test import Client  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from make_sample_package import build as build_sample  # noqa: E402

User = get_user_model()
results = []


def check(name, ok, detail=''):
    results.append((name, ok))
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (f' — {detail}' if detail else ''))
    return ok


def post(client, url, payload, auth, raw=False):
    resp = client.post(url, data=json.dumps(payload), content_type='application/json', **auth)
    return resp if raw else (resp.json() if resp.content else {})


def cleanup_previous():
    """清理上轮冒烟残留（比赛 + 比赛库），保证脚本可重复运行。"""
    from django.db import connections

    from apps.global_.competitions.models import Competition
    from apps.global_.packages.importer import _drop_database

    for comp in Competition.objects.filter(name='全流程冒烟赛'):
        db_name = comp.db_name
        comp.delete()  # 级联清掉成员/队伍/激活码/比赛包登记
        if db_name:
            connections.close_all()
            try:
                _drop_database(db_name)
            except Exception as exc:  # noqa: BLE001
                print(f'  [warn] drop {db_name}: {exc}')


def main():
    tmp_root = Path(tempfile.mkdtemp(prefix='gipfel_full_'))
    cleanup_previous()
    call_command('bootstrap_superadmin', 'full_admin', password='FullAdmin12345!', verbosity=0)
    for username in ('full_p1', 'full_p2', 'full_p3'):
        user, _ = User.objects.get_or_create(username=username, defaults={
            'email': f'{username}@smoke.local', 'display_name': username})
        user.set_password('Player12345!')
        user.save()

    client = Client()

    def login(username, password):
        resp = post(client, '/api/auth/login', {'username': username, 'password': password}, {})
        return {'HTTP_AUTHORIZATION': f'Bearer {resp.get("access", "")}'}

    admin = login('full_admin', 'FullAdmin12345!')
    p1 = login('full_p1', 'Player12345!')
    p2 = login('full_p2', 'Player12345!')
    p3 = login('full_p3', 'Player12345!')

    # ================================================== M2：组队 / 激活码
    print('\n== M2 账号与组队 ==')
    resp = client.post('/api/schools', data=json.dumps({'name': '冒烟大学'}),
                       content_type='application/json', **admin)
    school_id = resp.json().get('id')
    check('创建学校', resp.status_code in (200, 201), f'id={school_id}')

    resp = client.post('/api/competitions', data=json.dumps(
        {'name': '全流程冒烟赛', 'code': 'SMOKE', 'location': '线上'}),
        content_type='application/json', **admin)
    cid = resp.json().get('id')
    check('创建比赛（含比赛代码）', resp.status_code == 201 and resp.json().get('code') == 'SMOKE')

    # 导入示例比赛包（合同/产业插件 + 基础数据）
    zip_path = build_sample(tmp_root)
    upload = SimpleUploadedFile('sample.zip', zip_path.read_bytes(), content_type='application/zip')
    resp = client.post(f'/api/competitions/{cid}/package', {'file': upload}, **admin)
    check('导入比赛包', resp.status_code == 201, f'status={resp.status_code}')

    # 激活码加入比赛
    resp = post(client, f'/api/competitions/{cid}/invites',
                {'identity': 'PLAYER', 'maxUses': 10}, admin, raw=True)
    invite_code = resp.json().get('code')
    check('生成激活码', resp.status_code == 201 and bool(invite_code), invite_code)
    for token, name in ((p1, 'p1'), (p2, 'p2'), (p3, 'p3')):
        resp = post(client, '/api/invites/redeem', {'code': invite_code}, token, raw=True)
        check(f'激活码加入比赛（{name}）', resp.status_code == 201, str(resp.status_code))

    # 组队 + 组队码
    resp = post(client, f'/api/competitions/{cid}/teams',
                {'name': '一队', 'industryChoice': ['manufacturer'],
                 'industryAdjustAccepted': ['manufacturer']}, p1, raw=True)
    team1 = resp.json()
    check('队长建队（产业志愿）', resp.status_code == 201, f'id={team1.get("id")}')
    resp = post(client, f'/api/competitions/{cid}/teams/{team1["id"]}/join-codes',
                {'maxUses': 5}, p1, raw=True)
    join_code = resp.json().get('code')
    check('生成组队码', resp.status_code == 201 and bool(join_code), join_code)
    resp = post(client, f'/api/competitions/{cid}/teams/join', {'code': join_code}, p2, raw=True)
    check('组队码完成组队', resp.status_code == 201 and len(resp.json().get('members', [])) == 2)

    resp = post(client, f'/api/competitions/{cid}/teams',
                {'name': '二队', 'industryChoice': ['manufacturer']}, p3, raw=True)
    team2 = resp.json()
    check('队长建队（二队）', resp.status_code == 201)

    # 管理员手动调整产业 → 创建公司 + 初始值
    for tid in (team1['id'], team2['id']):
        resp = client.patch(f'/api/competitions/{cid}/teams/{tid}/industry',
                            data=json.dumps({'industryFinal': 'manufacturer'}),
                            content_type='application/json', **admin)
    check('管理员调整产业并建档公司', all(
        t.get('industryFinal') == 'manufacturer' for t in
        (client.get(f'/api/competitions/{cid}/teams', **admin).json())), '')

    companies = client.get(f'/api/competitions/{cid}/companies', **admin).json()
    comp1 = next((c for c in companies if c['teamId'] == team1['id']), None)
    comp2 = next((c for c in companies if c['teamId'] == team2['id']), None)
    check('公司映射（一队一公司）', bool(comp1 and comp2), f'{comp1} / {comp2}')

    table = client.get(f'/api/competitions/{cid}/companies/{comp1["id"]}/tables/finance', **p1).json()
    cash = next((f for f in table.get('fields', []) if f['key'] == 'cash'), {})
    check('产业初始值（cash=100000）', cash.get('values', {}) and 100000 in cash['values'].values(),
          str(cash.get('values')))

    # ================================================== M3：合同核心
    print('\n== M3 合同核心 ==')
    resp = post(client, f'/api/competitions/{cid}/fiscal-years/open', {}, admin, raw=True)
    fy1 = resp.json()
    check('开启财年 FY1', resp.status_code == 201 and fy1.get('year') == 1, str(fy1))

    resp = post(client, f'/api/competitions/{cid}/contracts', {
        'contractTypeKey': 'purchase', 'name': '冒烟采购 1',
        'parties': [{'role': 'buyer', 'companyId': comp1['id']},
                    {'role': 'seller', 'companyId': comp2['id']}],
        'inputs': {'product': 'p1', 'quantity': 10, 'unitPrice': 5},
    }, p1, raw=True)
    contract = resp.json()
    check('创建合同草稿（T1）', resp.status_code == 201 and contract.get('status') == 'DRAFT',
          f'id={contract.get("id")}')
    cid_contract = contract['id']

    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/submit', {}, p1, raw=True)
    check('提交草稿 + 检查（T2）', resp.status_code == 200
          and resp.json().get('status') == 'PENDING_PARTY', str(resp.status_code))

    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/confirm', {}, p1, raw=True)
    check('甲方确认（T3）', resp.status_code == 200 and resp.json().get('pendingPartyIndex') == 1,
          str(resp.json().get('pendingPartyIndex')))
    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/confirm', {}, p3, raw=True)
    data = resp.json()
    check('乙方确认 → 自动编号 + 自动执行 + 落账（T4/T5）',
          resp.status_code == 200 and data.get('status') == 'POSTED', str(data.get('status')))
    check('统一编号格式（D13）', (data.get('unifiedNumber') or '').startswith('PO-SMOKE-FY1-'),
          data.get('unifiedNumber'))

    detail = client.get(f'/api/competitions/{cid}/contracts/{cid_contract}', **p1).json()
    timeline = detail.get('timeline', [])
    confirms = [t for t in timeline if t['type'] == 'CONFIRM']
    check('确认时间线（谁/何时，§14.6）', len(confirms) == 2
          and all(c['actor'] for c in confirms), str(confirms))
    effects = client.get(f'/api/competitions/{cid}/contracts/{cid_contract}/effects', **p1).json()
    check('不可变效果审计（3 条）', len(effects) == 3 and all(e['roundNo'] == 0 for e in effects),
          str(len(effects)))

    table = client.get(f'/api/competitions/{cid}/companies/{comp1["id"]}/tables/finance', **p1).json()
    cash = next((f for f in table['fields'] if f['key'] == 'cash'), {})
    check('落账改写买方现金（-50）', 99950 in cash['values'].values(), str(cash['values']))

    logs = client.get(f'/api/competitions/{cid}/logs/fields?contractId={cid_contract}', **admin).json()
    check('字段日志（CONTRACT_POST）', logs.get('total', 0) >= 3
          and any(i['source'] == 'CONTRACT_POST' for i in logs['items']), str(logs.get('total')))

    # 冻结守卫（§7.4，决策 D10）：被冻结合同字段拒绝其他途径修改
    resp = client.patch(f'/api/competitions/{cid}/companies/{comp1["id"]}/fields',
                        data=json.dumps({'fieldKey': 'cash', 'value': 1}),
                        content_type='application/json', **admin)
    check('冻结字段拒绝手工修改（§7.4）', resp.status_code == 400, str(resp.status_code))
    resp = client.patch(f'/api/competitions/{cid}/companies/{comp1["id"]}/fields',
                        data=json.dumps({'fieldKey': 'capacity', 'value': 12}),
                        content_type='application/json', **admin)
    check('未冻结字段可手工修改', resp.status_code == 200, str(resp.status_code))

    # ================================================== M4：修改流程
    print('\n== M4 修改申请（T6–T10） ==')
    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/request-modify',
                {'reason': '数量录入错误'}, p1, raw=True)
    check('T6 申请修改（理由必填）', resp.status_code == 201
          and resp.json().get('status') == 'MOD_APPLYING', str(resp.status_code))
    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/request-modify',
                {'reason': ''}, p1, raw=True)
    check('T6 守卫：理由必填被拒', resp.status_code == 400)

    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/modify/review',
                {'action': 'approve'}, admin, raw=True)
    check('T7 超管通过 → 修改中', resp.status_code == 200
          and resp.json().get('status') == 'MOD_EDITING', str(resp.status_code))
    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/modify/other-party',
                {'action': 'approve'}, p3, raw=True)
    check('T8 其他方逐一通过', resp.status_code == 200, str(resp.status_code))
    resp = post(client, f'/api/competitions/{cid}/contracts/{cid_contract}/modify/submit',
                {'inputs': {'product': 'p1', 'quantity': 20, 'unitPrice': 5}}, p1, raw=True)
    data = resp.json()
    check('T9/T10 回滚 + 重检查 + 自动执行 + 重落账', resp.status_code == 200
          and data.get('status') == 'POSTED' and data.get('roundNo') == 1,
          f'status={data.get("status")} round={data.get("roundNo")}')

    logs = client.get(f'/api/competitions/{cid}/logs/fields?contractId={cid_contract}', **admin).json()
    sources = {i['source'] for i in logs['items']}
    check('回滚与重落账字段日志', 'CONTRACT_ROLLBACK' in sources and 'CONTRACT_REPOST' in sources,
          str(sources))

    # ================================================== M4：财年 / 补录
    print('\n== M4 财年与补录 ==')
    resp = post(client, f'/api/competitions/{cid}/fiscal-years/close', {}, admin, raw=True)
    check('结束财年（自动备份）', resp.status_code == 200, str(resp.status_code))
    backups = client.get(f'/api/competitions/{cid}/fiscal-years/{fy1["id"]}/backups', **admin).json()
    check('备份快照（各公司一张）', len(backups) >= 2 and len([b for b in backups if b.get('snapshot')]) >= 2,
          str(len(backups)))

    resp = post(client, f'/api/competitions/{cid}/contracts', {
        'contractTypeKey': 'loan', 'name': '补录贷款', 'isBackfill': True,
        'fiscalYearId': fy1['id'],
        'parties': [{'role': 'lender', 'companyId': comp2['id']},
                    {'role': 'borrower', 'companyId': comp1['id']}],
        'inputs': {'principal': 100, 'rate': 0.05},
    }, p3, raw=True)
    backfill = resp.json()
    check('创建补录合同 → 补录审核（D14）', resp.status_code == 201
          and backfill.get('status') == 'BACKFILL_REVIEW', str(backfill.get('status')))
    resp = post(client, f'/api/competitions/{cid}/contracts/{backfill["id"]}/backfill/review',
                {'action': 'approve'}, admin, raw=True)
    check('补录超管审核通过 → 草稿', resp.status_code == 200
          and resp.json().get('status') == 'DRAFT', str(resp.json().get('status')))

    post(client, f'/api/competitions/{cid}/contracts/{backfill["id"]}/submit', {}, p3, raw=True)
    post(client, f'/api/competitions/{cid}/contracts/{backfill["id"]}/confirm', {}, p3, raw=True)
    resp = post(client, f'/api/competitions/{cid}/contracts/{backfill["id"]}/confirm', {}, p1, raw=True)
    data = resp.json()
    check('补录执行（基准=财年末快照）→ 落账', resp.status_code == 200
          and data.get('status') == 'POSTED', str(data.get('status')))
    logs = client.get(f'/api/competitions/{cid}/logs/fields?contractId={backfill["id"]}', **admin).json()
    sources = {i['source'] for i in logs['items']}
    check('非财年定时器字段自动同步（BACKFILL_SYNC）', 'BACKFILL_SYNC' in sources, str(sources))

    # ================================================== M5：结算 / 奖牌
    print('\n== M5 结算评分与电子奖牌 ==')
    post(client, f'/api/competitions/{cid}/settlement/config',
         {'kind': 'criterion', 'name': '现金', 'fieldKey': 'cash',
          'aggregation': 'SUM', 'weight': 1.0}, admin, raw=True)
    post(client, f'/api/competitions/{cid}/settlement/config',
         {'kind': 'criterion', 'name': '产能', 'fieldKey': 'capacity',
          'aggregation': 'LATEST', 'weight': 0.5}, admin, raw=True)
    post(client, f'/api/competitions/{cid}/settlement/config',
         {'kind': 'award', 'awardLevel': '一等奖', 'rankFrom': 1, 'rankTo': 2}, admin, raw=True)
    resp = post(client, f'/api/competitions/{cid}/settlement/run', {}, admin, raw=True)
    check('开始结算（评分准则计算）', resp.status_code == 201, str(resp.status_code))
    result = client.get(f'/api/competitions/{cid}/settlement/result', **admin).json()
    entries = result.get('entries', [])
    check('结算结果（名次/得分/获奖）', len(entries) >= 2
          and any(e.get('awardLevel') for e in entries), str(entries)[:200])

    awards = client.get('/api/me/awards', **p1).json()
    check('获奖信息同步个人档案', bool(awards) and awards[0].get('medalId'), str(awards)[:200])
    if awards and awards[0].get('medalId'):
        medal = client.get(f'/api/me/medals/{awards[0]["medalId"]}', **p1).json()
        check('电子奖牌在线展示（D12）', bool(medal.get('displayAsset')), medal.get('displayName', ''))
    else:
        check('电子奖牌在线展示（D12）', False, '无奖牌记录')

    # ================================================== M6：消息 / 权限
    print('\n== M6 消息与权限 ==')
    messages = client.get('/api/me/messages', **p1).json()
    check('消息中心（跨比赛汇总）', bool(messages), f'{len(messages)} 条')
    resp = client.get('/api/logs/network', **p1)
    check('网络日志仅系统超管（§15.2）', resp.status_code == 403, str(resp.status_code))
    resp = client.get(f'/api/competitions/{cid}/logs/fields', **p2)
    check('字段日志按公司可见性过滤', resp.status_code == 200, str(resp.status_code))

    failed = [n for n, ok in results if not ok]
    print(f'\n== 结果：{len(results) - len(failed)}/{len(results)} 通过 ==')
    if failed:
        print('失败项：' + '；'.join(failed))
        sys.exit(1)


if __name__ == '__main__':
    main()
