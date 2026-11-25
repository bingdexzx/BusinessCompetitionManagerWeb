"""导入时公式循环：报告提示 + 拒绝计算。"""

import hashlib
import tempfile
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.global_.competitions.models import Competition
from apps.global_.packages import importer
from apps.global_.packages.models import Package
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_cyclepkg'
register_competition_db(ALIAS)

User = get_user_model()

INDUSTRY_PLUGIN = '''\
"""测试用循环公式产业插件。"""

INDUSTRY_KEY = 'cyc'
INDUSTRY_NAME = '循环产业'

FIELDS = [
    {'key': 'a', 'name': '甲', 'type': 'NUMBER', 'table': 'finance', 'formula': 'b + 1'},
    {'key': 'b', 'name': '乙', 'type': 'NUMBER', 'table': 'finance', 'formula': 'a + 1'},
    {'key': 'base', 'name': '基数', 'type': 'NUMBER', 'table': 'finance'},
    {'key': 'total', 'name': '合计', 'type': 'NUMBER', 'table': 'finance',
     'formula': 'base * 2'},
]


def initial_values():
    return {'base': 10}
'''


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_package(root: Path) -> Path:
    plugins = root / 'plugins'
    plugins.mkdir(parents=True)
    plugin = plugins / 'industry_cyc.py'
    plugin.write_text(INDUSTRY_PLUGIN, encoding='utf-8')

    manifest = root / 'manifest.yaml'
    manifest.write_text(
        'packageVersion: "1.0"\n'
        'plugins:\n'
        '  - file: plugins/industry_cyc.py\n'
        '    kind: INDUSTRY\n'
        '    key: cyc\n'
        '    name: 循环产业\n'
        '    version: 1.0.0\n'
        f'    sha256: {_sha(plugin)}\n',
        encoding='utf-8',
    )

    zip_path = root / 'package.zip'
    with ZipFile(zip_path, 'w', ZIP_DEFLATED) as zf:
        for file in (manifest, plugin):
            zf.write(file, file.relative_to(root).as_posix())
    return zip_path


class ImportCycleFormulaTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='循环导入赛', code='CYCIMP', db_name=ALIAS)
        self.user = User.objects.create_user(
            username='cycuser', password='x' * 12, email='cyc@example.com')
        self._tmp = tempfile.TemporaryDirectory(prefix='pkg_cyc_')
        self.zip_path = _build_package(Path(self._tmp.name))

    def tearDown(self):
        ctx.clear_request_context()
        self._tmp.cleanup()

    def _import(self) -> Package:
        with mock.patch.object(
                importer.provisioning, 'database_exists', return_value=True), \
             mock.patch.object(
                importer.provisioning, 'create_competition_database',
                side_effect=importer.provisioning.ensure_competition_db), \
             mock.patch.object(
                importer.default_storage, 'save', return_value='packages/cyc.zip'):
            return importer.import_package(
                competition=self.competition, zip_path=str(self.zip_path),
                file_name='package.zip', user=self.user)

    def test_import_warns_and_refuses_cycle(self):
        from apps.competition.companies.models import Company
        from apps.competition.industries.models import CompanyFieldValue, IndustryField
        from apps.competition.industries.services import recompute_company_fields

        package = self._import()
        report = package.import_report
        self.assertEqual(report['status'], 'SUCCESS', report['errors'])

        warnings = '\n'.join(report['warnings'])
        self.assertIn('公式循环', warnings)
        self.assertIn('a → b → a', warnings)
        self.assertIn('已拒绝计算', warnings)

        ctx.set_competition_context(self.competition.pk, ALIAS)
        field_a = IndustryField.objects.get(field_key='a')
        field_b = IndustryField.objects.get(field_key='b')
        self.assertTrue(field_a.meta.get('formulaCycle'))
        self.assertTrue(field_b.meta.get('formulaCycle'))
        # 非循环字段不受影响
        self.assertFalse(IndustryField.objects.get(field_key='total').meta.get('formulaCycle'))

        company = Company.objects.create(name='循环公司')
        CompanyFieldValue.objects.create(
            company=company, field_key='base', value=10)
        recompute_company_fields(company)

        # 循环字段拒绝计算（不写值），非循环字段照常算
        self.assertFalse(CompanyFieldValue.objects.filter(
            company=company, field_key__in=['a', 'b']).exists())
        self.assertEqual(
            CompanyFieldValue.objects.get(
                company=company, field_key='total').value, 20)
