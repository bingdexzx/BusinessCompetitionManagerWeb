"""重导入幂等（端到端）：同一份比赛包导入两次，第二次不再重复建合同（2026-10 决策）。

真实走一遍 解压 → manifest/SHA 校验 → AST 扫描 → 插件注册 → 产业字段迁移 → 合同实例导入。
只有两处外部副作用被替身化：``CREATE DATABASE``（测试库由测试运行器管理）与
media 落盘（避免测试污染 media/）。
"""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import Workbook

from apps.common import context as ctx
from apps.competition.contracts.models import Contract
from apps.global_.competitions.models import Competition
from apps.global_.packages import importer
from apps.global_.packages.models import Package
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()

CONTRACT_PLUGIN = '''\
"""测试用采购合同插件。"""

CONTRACT_KEY = "purchase"
CONTRACT_NAME = "采购合同"
NUMBER_PREFIX = "PO"

PARTY_ROLES = [
    {"role": "buyer", "label": "买方"},
    {"role": "seller", "label": "卖方"},
]

INPUT_SCHEMA = [
    {"key": "quantity", "label": "数量", "type": "NUMBER"},
]


def check(ctx):
    return []


def apply(ctx):
    return []
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_package(root: Path) -> Path:
    """生成最小可用比赛包（1 个合同插件 + contracts.xlsx + manifest.yaml）。"""
    plugins = root / 'plugins'
    sheets = root / 'sheets'
    plugins.mkdir(parents=True)
    sheets.mkdir(parents=True)

    plugin = plugins / 'contract_purchase.py'
    plugin.write_text(CONTRACT_PLUGIN, encoding='utf-8')

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'contracts'
    sheet.append(['contractTypeKey', 'name', 'partiesJSON', 'inputsJSON'])
    sheet.append([
        'purchase', '首笔采购',
        json.dumps([{'role': 'buyer', 'companyName': '买方公司'},
                    {'role': 'seller', 'companyName': '卖方公司'}], ensure_ascii=False),
        json.dumps({'quantity': 10}, ensure_ascii=False),
    ])
    contracts = sheets / 'contracts.xlsx'
    workbook.save(contracts)

    manifest = root / 'manifest.yaml'
    manifest.write_text(
        'packageVersion: "1.0"\n'
        'plugins:\n'
        '  - file: plugins/contract_purchase.py\n'
        '    kind: CONTRACT\n'
        '    key: purchase\n'
        '    name: 采购合同\n'
        '    version: 1.0.0\n'
        f'    sha256: {_sha256(plugin)}\n'
        'sheets:\n'
        '  - file: sheets/contracts.xlsx\n'
        f'    sha256: {_sha256(contracts)}\n',
        encoding='utf-8',
    )

    zip_path = root / 'package.zip'
    with ZipFile(zip_path, 'w', ZIP_DEFLATED) as zf:
        for file in (manifest, plugin, contracts):
            zf.write(file, file.relative_to(root).as_posix())
    return zip_path


class PackageReimportTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='重导入测试赛', code='REIMPORT', db_name=ALIAS)
        self.cid = self.competition.pk
        self.user = User.objects.create_user(
            username='pkguser', password='x' * 12, email='pkguser@example.com')
        self._tmp = tempfile.TemporaryDirectory(prefix='pkg_test_')
        self.zip_path = _build_package(Path(self._tmp.name))
        # 公司不再由包导入：预置参与方公司
        ctx.set_competition_context(self.cid, ALIAS)
        from apps.competition.companies.models import Company
        Company.objects.create(name='买方公司', industry_key='')
        Company.objects.create(name='卖方公司', industry_key='')
        ctx.clear_request_context()

    def tearDown(self):
        ctx.clear_request_context()
        self._tmp.cleanup()

    def _import(self) -> Package:
        """导入比赛包（替身：建库 + media 落盘）。"""
        with mock.patch.object(
                importer.provisioning, 'database_exists', return_value=True), \
             mock.patch.object(
                importer.provisioning, 'create_competition_database',
                side_effect=importer.provisioning.ensure_competition_db), \
             mock.patch.object(
                importer.default_storage, 'save', return_value='packages/probe.zip'):
            return importer.import_package(
                competition=self.competition, zip_path=str(self.zip_path),
                file_name='package.zip', user=self.user)

    def _contracts(self):
        ctx.set_competition_context(self.cid, ALIAS)
        return Contract.objects.all()

    def test_first_import_creates_contracts(self):
        package = self._import()
        report = package.import_report
        self.assertEqual(report['status'], 'SUCCESS', report['errors'])
        self.assertEqual(report['contractsCreated'], 1)
        self.assertEqual(report['contractsSkipped'], 0)
        self.assertEqual(self._contracts().count(), 1)

        ctx.set_competition_context(self.cid, ALIAS)
        self.competition.refresh_from_db()
        self.assertEqual(self.competition.status, Competition.Status.PACKAGE_IMPORTED)

    def test_reimport_does_not_duplicate_contracts(self):
        self._import()
        package = self._import()          # 同一份包再来一次
        report = package.import_report
        self.assertEqual(report['status'], 'SUCCESS', report['errors'])
        self.assertEqual(report['contractsCreated'], 0)   # 不再重复建
        self.assertEqual(report['contractsSkipped'], 1)
        self.assertEqual(self._contracts().count(), 1)    # 合同没有翻倍
        self.assertTrue(any('已存在' in w for w in report['warnings']))

        # 两次导入都留有历史记录（导入历史不合并）
        self.assertEqual(Package.objects.filter(competition=self.competition).count(), 2)

    def test_reimport_after_contract_deleted_still_skips(self):
        self._import()
        from django.utils import timezone

        ctx.set_competition_context(self.cid, ALIAS)
        Contract.objects.update(deleted_at=timezone.now())
        package = self._import()
        self.assertEqual(package.import_report['contractsCreated'], 0)
        self.assertEqual(self._contracts().count(), 1)
