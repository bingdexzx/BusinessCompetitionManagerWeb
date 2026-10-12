"""M1 冒烟验证：比赛包导入全流程（成功链路 + 失败回滚链路）。

运行：.venv\\Scripts\\python.exe scripts\\smoke_m1.py
"""

import io
import json
import os
import shutil
import sys
import tempfile

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))

import django  # noqa: E402

django.setup()

import psycopg2  # noqa: E402
import yaml  # noqa: E402
from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connections  # noqa: E402
from django.test import Client  # noqa: E402

sys.path.insert(0, os.path.dirname(__file__))
from make_sample_package import build as build_sample  # noqa: E402

User = get_user_model()
results = []


def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('  [PASS] ' if ok else '  [FAIL] ') + name + (f' — {detail}' if detail else ''))


def tables_in(db_name):
    cfg = settings.DATABASES['default']
    conn = psycopg2.connect(dbname=db_name, user=cfg['USER'], password=cfg['PASSWORD'],
                            host=cfg['HOST'], port=cfg['PORT'])
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    names = {r[0] for r in cur.fetchall()}
    conn.close()
    return names


def build_bad_package(path: Path):
    """构造坏包：插件含 os.system（AST 黑名单）+ 缺必备接口。"""
    plugin = (
        'import os\n'
        'CONTRACT_KEY = "evil"\n'
        'CONTRACT_NAME = "恶意合同"\n'
        'PARTY_ROLES = []\n'
        'INPUT_SCHEMA = []\n'
        'def check(ctx):\n    os.system("whoami")\n    return []\n'
        'def apply(ctx):\n    return []\n'
    )
    manifest = {
        'packageVersion': '1.0',
        'plugins': [{'file': 'plugins/contract_evil.py', 'kind': 'CONTRACT',
                     'key': 'evil', 'name': '恶意合同', 'version': '1.0.0'}],
        'sheets': [],
    }
    with ZipFile(path, 'w', ZIP_DEFLATED) as zf:
        zf.writestr('manifest.yaml', yaml.safe_dump(manifest, allow_unicode=True))
        zf.writestr('plugins/contract_evil.py', plugin)


def main():
    tmp_root = Path(tempfile.mkdtemp(prefix='gipfel_m1_'))
    call_command('bootstrap_superadmin', 'm1_admin', password='M1Admin12345!', verbosity=0)
    client = Client()

    # ---------------------------------------------------------- 0. 登录
    resp = client.post('/api/auth/login', data=json.dumps(
        {'username': 'm1_admin', 'password': 'M1Admin12345!'}), content_type='application/json')
    auth = {'HTTP_AUTHORIZATION': f'Bearer {resp.json().get("access", "")}'}
    check('登录', resp.status_code == 200, f'status={resp.status_code}')

    # ---------------------------------------------------------- 1. 建赛
    resp = client.post('/api/competitions', data=json.dumps({'name': 'M1冒烟导入赛'}),
                       content_type='application/json', **auth)
    cid = resp.json().get('id')
    db_name = resp.json().get('dbName')
    check('创建比赛', resp.status_code == 201 and db_name == f'comp_{cid}', f'id={cid} db={db_name}')

    # ---------------------------------------------------------- 2. 生成并上传示例包
    zip_path = build_sample(tmp_root)
    upload = SimpleUploadedFile('sample.zip', zip_path.read_bytes(), content_type='application/zip')
    resp = client.post(f'/api/competitions/{cid}/package', {'file': upload}, **auth)
    ok = resp.status_code == 201
    check('上传比赛包（导入成功）', ok, f'status={resp.status_code} detail={str(resp.json().get("details"))[:200]}')
    report = resp.json().get('report', {}) if ok else {}
    check('导入报告 SUCCESS', report.get('status') == 'SUCCESS', f'status={report.get("status")}')
    check('导入报告记录建库', report.get('createdDatabase', '').startswith(db_name),
          str(report.get('createdDatabase')))
    check('导入报告：3 个插件', len(report.get('plugins', [])) == 3, str(len(report.get('plugins', []))))
    check('导入报告：字段迁移', len(report.get('fieldMigrations', [])) == 1
          and report['fieldMigrations'][0]['added'] == 3, str(report.get('fieldMigrations')))

    # ---------------------------------------------------------- 3. 比赛库数据落地
    tables = tables_in(db_name)
    check('比赛库含 basedata 表', 'basedata_fuel' in tables and 'basedata_productionline' in tables)

    # 比赛状态自动推进
    resp = client.get(f'/api/competitions/{cid}', **auth)
    check('状态自动推进到 PACKAGE_IMPORTED', resp.json().get('status') == 'PACKAGE_IMPORTED',
          resp.json().get('status'))

    # ---------------------------------------------------------- 4. 合同类型接口 + 插件管理
    resp = client.get(f'/api/competitions/{cid}/contract-types', **auth)
    types = resp.json() if resp.status_code == 200 else []
    keys = {t.get('key') for t in types}
    check('合同类型接口暴露 schema', resp.status_code == 200 and keys == {'purchase', 'loan'},
          str(keys))
    purchase = next((t for t in types if t.get('key') == 'purchase'), {})
    check('合同类型含参与方/输入 schema',
          bool(purchase.get('partyRoles')) and bool(purchase.get('inputSchema'))
          and purchase.get('numberPrefix') == 'PO', str(purchase.get('numberPrefix')))

    resp = client.get('/api/plugins', **auth)
    plugins = resp.json() if resp.status_code == 200 else []
    check('插件注册表（含审计）', len(plugins) == 3 and all(p.get('auditTrail') for p in plugins),
          f'条数={len(plugins)}')

    # ---------------------------------------------------------- 5. 比赛库内数据核验（抽样）
    from apps.common import context as ctx
    from apps.competition import provisioning
    from apps.competition.basedata.models import Fuel, ProductionLine
    from apps.competition.companies.models import Company
    from apps.competition.contracts.models import Contract
    from apps.competition.fieldlogs.models import FieldLog
    from apps.competition.industries.models import IndustryField
    alias = provisioning.ensure_competition_db(db_name)
    ctx.set_competition_context(cid, alias)
    try:
        check('基础数据不再随包导入（燃料为空）', Fuel.objects.count() == 0,
              f'count={Fuel.objects.count()}')
        check('基础数据改由数据管理页维护（生产线为空）', ProductionLine.objects.count() == 0)
        fields = {f.field_key: f for f in IndustryField.objects.all()}
        check('产业字段迁移', set(fields) == {'cash', 'capacity', 'loan_limit'}, str(set(fields)))
        check('公式字段标记', fields.get('loan_limit') is not None and fields['loan_limit'].is_calculated)
        check('字段日志 SCHEMA_CHANGE（3 条）',
              FieldLog.objects.filter(event='SCHEMA_CHANGE').count() == 3,
              f'count={FieldLog.objects.filter(event="SCHEMA_CHANGE").count()}')
        contracts = list(Contract.objects.all())
        check('合同实例导入（草稿态）', len(contracts) == 2
              and all(c.status == 'DRAFT' for c in contracts), f'count={len(contracts)}')
        check('合同参与方公司自动建档', Company.objects.count() == 2, f'count={Company.objects.count()}')
    finally:
        ctx.clear_request_context()

    # ---------------------------------------------------------- 6. 失败链路：坏包 → 422 + 回滚
    bad_zip = tmp_root / 'bad.zip'
    build_bad_package(bad_zip)
    upload = SimpleUploadedFile('bad.zip', bad_zip.read_bytes(), content_type='application/zip')
    resp = client.post(f'/api/competitions/{cid}/package', {'file': upload}, **auth)
    check('坏包被拒绝（422）', resp.status_code == 422, f'status={resp.status_code}')
    details = resp.json().get('details', {}) if resp.status_code == 422 else {}
    errs = ' '.join(details.get('errors', []))
    check('报告含 AST 黑名单问题', '禁止' in errs and 'os' in errs, errs[:150])
    check('坏包登记 FAILED 报告', any(
        p.get('status') == 'FAILED'
        for p in (client.get(f'/api/competitions/{cid}/packages', **auth).json() or [])))

    # 坏包未破坏既有数据
    ctx.set_competition_context(cid, provisioning.ensure_competition_db(db_name))
    try:
        check('失败导入不影响既有数据', Fuel.objects.count() == 0
              and IndustryField.objects.count() == 3
              and Contract.objects.count() == 2)
    finally:
        ctx.clear_request_context()

    # ---------------------------------------------------------- 7. 权限：普通用户不可上传
    resp = client.post('/api/auth/register', data=json.dumps(
        {'username': 'm1_player', 'password': 'Player12345!', 'email': 'm1_player@example.com'}),
        content_type='application/json')
    resp = client.post('/api/auth/login', data=json.dumps(
        {'username': 'm1_player', 'password': 'Player12345!'}), content_type='application/json')
    player_auth = {'HTTP_AUTHORIZATION': f'Bearer {resp.json().get("access", "")}'}
    upload = SimpleUploadedFile('sample.zip', zip_path.read_bytes(), content_type='application/zip')
    resp = client.post(f'/api/competitions/{cid}/package', {'file': upload}, **player_auth)
    check('权限矩阵：普通用户不可导入比赛包', resp.status_code in (403, 404), f'status={resp.status_code}')

    # ---------------------------------------------------------- 8. 清理
    from apps.global_.competitions.models import Competition
    comp = Competition.objects.filter(pk=cid).first()
    if comp:
        name = comp.db_name
        comp.delete()
        connections.close_all()
        cfg = settings.DATABASES['default']
        conn = psycopg2.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'],
                                host=cfg['HOST'], port=cfg['PORT'])
        conn.autocommit = True
        conn.cursor().execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.close()
    User.objects.filter(username__in=['m1_admin', 'm1_player']).delete()
    shutil.rmtree(tmp_root, ignore_errors=True)

    failed = [r for r in results if not r[1]]
    print(f'\nM1 冒烟：{len(results) - len(failed)}/{len(results)} 通过')
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
