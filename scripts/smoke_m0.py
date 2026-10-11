"""M0 冒烟验证（对着开发库跑）：

1. 引导系统超管 → 登录（JWT + 设备登记）；
2. 注册用户、建学校；
3. 创建比赛 → 自动建库 comp_<id> → 校验比赛域表齐备、无全局域表；
4. 指派比赛超管（D9）；
5. 网络日志中心查询 + 脱敏校验；
6. 清理冒烟数据。

运行：.venv\\Scripts\\python.exe scripts\\smoke_m0.py
"""

import json
import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.test import Client  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

import psycopg2  # noqa: E402
from django.conf import settings  # noqa: E402

User = get_user_model()
results = []


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (f' — {detail}' if detail else ''))


def main():
    # ------------------------------------------------------------ 0. 引导
    call_command('bootstrap_superadmin', 'smoke_admin', password='Smoke12345!', verbosity=0)
    client = Client()

    # ------------------------------------------------------------ 1. 登录
    resp = client.post('/api/auth/login', data=json.dumps({'username': 'smoke_admin', 'password': 'Smoke12345!'}),
                       content_type='application/json')
    check('登录签发 JWT', resp.status_code == 200 and 'access' in resp.json(), f'status={resp.status_code}')
    token = resp.json().get('access', '')
    auth = {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    # ------------------------------------------------------------ 2. 学校
    resp = client.post('/api/schools', data=json.dumps({'name': '冒烟大学', 'region': '测试区'}),
                       content_type='application/json', **auth)
    check('创建学校', resp.status_code in (200, 201), f'status={resp.status_code}')
    school_id = resp.json().get('id')

    # 注册普通用户
    resp = client.post('/api/auth/register', data=json.dumps(
        {'username': 'smoke_player', 'password': 'Player12345!', 'email': 'smoke_player@example.com',
         'displayName': '选手甲', 'schoolId': school_id}),
        content_type='application/json')
    check('注册用户（邮箱+选学校）', resp.status_code == 201, f'status={resp.status_code}')

    # 重复邮箱应被拒绝
    resp = client.post('/api/auth/register', data=json.dumps(
        {'username': 'smoke_player2', 'password': 'Player12345!', 'email': 'smoke_player@example.com',
         'displayName': '选手乙'}),
        content_type='application/json')
    check('重复邮箱被拒绝', resp.status_code == 400, f'status={resp.status_code}')

    # ------------------------------------------------------------ 3. 创建比赛 + 自动建库
    resp = client.post('/api/competitions', data=json.dumps({
        'name': 'M0冒烟测试赛', 'location': '线上', 'staffingInfo': '主席团3人',
        'hostSchoolId': school_id, 'coverImage': 'https://example.com/cover.png',
    }), content_type='application/json', **auth)
    ok = resp.status_code == 201
    check('创建比赛（自动建库）', ok, f'status={resp.status_code}')
    data = resp.json()
    cid, db_name = data.get('id'), data.get('dbName')
    check('比赛库命名 comp_<id>', db_name == f'comp_{cid}', f'dbName={db_name}')

    # 比赛库表清单
    cfg = settings.DATABASES['default']
    conn = psycopg2.connect(dbname=db_name, user=cfg['USER'], password=cfg['PASSWORD'],
                            host=cfg['HOST'], port=cfg['PORT'])
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()
    want = {'companies_company', 'industries_industryfield', 'industries_companyfieldvalue',
            'contracts_contract', 'contracts_contractconfirmation', 'contracts_contractmodrequest',
            'contracts_contractfieldeffect', 'ledger_contractfreeze', 'fiscal_fiscalyear',
            'fiscal_fiscalyearbackup', 'fieldlogs_fieldlog', 'comp_messages_message', 'comp_audit_auditlog'}
    check('比赛域表齐备', want <= tables, f'缺失={sorted(want - tables)}')
    leaked = {'accounts_user', 'logs_networklog'} & tables
    check('比赛库不含全局域表', not leaked, f'误入={sorted(leaked)}')

    # ------------------------------------------------------------ 4. 指派比赛超管（D9）
    resp = client.post(f'/api/competitions/{cid}/members', data=json.dumps({
        'username': 'smoke_player', 'identity': 'COMP_SUPER_ADMIN', 'managedCompanies': [],
    }), content_type='application/json', **auth)
    check('指派比赛超管', resp.status_code == 201, f'status={resp.status_code}')

    # 身份切换可见性：普通用户应能看到自己有身份的比赛
    resp = client.post('/api/auth/login', data=json.dumps({'username': 'smoke_player', 'password': 'Player12345!'}),
                       content_type='application/json')
    player_token = resp.json().get('access', '')
    resp = client.get('/api/competitions', **{'HTTP_AUTHORIZATION': f'Bearer {player_token}'})
    check('一账号多身份：按身份列出比赛', resp.status_code == 200 and any(c['id'] == cid for c in resp.json()),
          f'status={resp.status_code}')

    # 生命周期转移
    resp = client.post(f'/api/competitions/{cid}/transition', data=json.dumps({'target': 'PACKAGE_IMPORTED'}),
                       content_type='application/json', **auth)
    check('生命周期转移 CREATED→PACKAGE_IMPORTED', resp.status_code == 200 and resp.json()['status'] == 'PACKAGE_IMPORTED',
          f'status={resp.status_code}')

    # ------------------------------------------------------------ 5. 网络日志 + 脱敏
    resp = client.get('/api/logs/network?limit=100', **auth)
    ok = resp.status_code == 200
    items = resp.json().get('items', []) if ok else []
    check('网络日志查询（仅系统超管）', ok and len(items) > 5, f'条数={len(items)}')

    login_logs = [i for i in items if i['path'] == '/api/auth/login']
    digest_text = ' '.join((i.get('payloadDigest') or '') + (i.get('responseDigest') or '') for i in login_logs)
    check('登录日志脱敏（无明文密码）', 'Player12345!' not in digest_text and 'Smoke12345!' not in digest_text)
    check('登录日志含 [REDACTED]', '[REDACTED]' in digest_text)
    check('日志含设备快照', all(i.get('deviceSnapshot') for i in items[:5]))
    check('日志含 traceId', all(i.get('traceId') for i in items[:5]))

    resp = client.get('/api/logs/devices', **auth)
    check('设备管理（仅系统超管）', resp.status_code == 200 and len(resp.json()) >= 2)

    # 非超管不可查网络日志
    resp = client.get('/api/logs/network', **{'HTTP_AUTHORIZATION': f'Bearer {player_token}'})
    check('权限矩阵：普通用户不可查网络日志', resp.status_code == 403, f'status={resp.status_code}')

    # ------------------------------------------------------------ 6. 清理冒烟数据
    from django.db import connections
    from apps.global_.competitions.models import Competition
    comp = Competition.objects.filter(pk=cid).first()
    if comp:
        name = comp.db_name
        comp.delete()
        connections.close_all()  # 释放到比赛库的连接，否则 DROP DATABASE 会被占用
        cfg = settings.DATABASES['default']
        conn = psycopg2.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
                                host=cfg['HOST'], port=cfg['PORT'])
        conn.autocommit = True
        conn.cursor().execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.close()
    User.objects.filter(username__in=['smoke_admin', 'smoke_player']).delete()

    # ------------------------------------------------------------ 汇总
    failed = [r for r in results if not r[1]]
    print(f"\nM0 冒烟：{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
