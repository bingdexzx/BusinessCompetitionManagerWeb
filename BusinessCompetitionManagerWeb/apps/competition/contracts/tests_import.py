"""合同实例导入幂等测试（比赛包重导入去重，2026-10 决策）。

同一份比赛包重复导入不得产生重复合同：按「类型 + 名称 + 参与方 + 输入」指纹跳过。
"""

from django.test import TestCase
from django.utils import timezone

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import services as contract_services
from apps.competition.contracts.fingerprint import contract_fingerprint
from apps.competition.contracts.models import Contract
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class _FakePurchaseModule:
    """最小合同插件替身（导入只用到 PARTY_ROLES / INPUT_SCHEMA）。"""

    CONTRACT_KEY = 'purchase'
    CONTRACT_NAME = '采购合同'
    PARTY_ROLES = [{'role': 'buyer'}, {'role': 'seller'}]
    INPUT_SCHEMA = [{'key': 'quantity', 'type': 'NUMBER'}]


class ContractImportDedupeTests(TestCase):
    databases = {'default', ALIAS}

    def setUp(self):
        ctx.set_competition_context(1, ALIAS)
        # 比赛包不再自动建公司：先准备参与方公司
        Company.objects.create(name='买方公司', industry_key='')
        Company.objects.create(name='卖方公司', industry_key='')
        self.rows = [{
            'contractTypeKey': 'purchase',
            'name': '首笔采购',
            'partiesJSON': (
                '[{"role":"buyer","companyName":"买方公司"},'
                '{"role":"seller","companyName":"卖方公司"}]'
            ),
            'inputsJSON': '{"quantity": 10}',
        }]
        self.modules = {'purchase': {'module': _FakePurchaseModule, 'version': '1.0.0'}}

    def tearDown(self):
        ctx.clear_request_context()

    def _import(self, rows=None):
        ctx.set_competition_context(1, ALIAS)
        return contract_services.import_contract_instances(
            rows if rows is not None else self.rows, self.modules, user=None)

    def _count(self) -> int:
        ctx.set_competition_context(1, ALIAS)
        return Contract.objects.count()

    # ------------------------------------------------------------ 指纹

    def test_fingerprint_ignores_non_identity_party_keys(self):
        """参与方的展示字段（companyName/confirmOrder/confirmAt）不影响指纹。"""
        first = contract_fingerprint('purchase', 'A', [
            {'role': 'buyer', 'companyId': 1, 'companyName': '甲', 'confirmOrder': 0}, ], {})
        second = contract_fingerprint('purchase', 'A', [
            {'role': 'buyer', 'companyId': 1, 'companyName': '甲（改名）', 'confirmAt': 'x'}, ], {})
        self.assertEqual(first, second)

    def test_fingerprint_changes_with_content(self):
        base = contract_fingerprint('purchase', 'A', [{'role': 'buyer', 'companyId': 1}], {'q': 1})
        self.assertNotEqual(
            base, contract_fingerprint('purchase', 'A', [{'role': 'buyer', 'companyId': 1}], {'q': 2}))
        self.assertNotEqual(
            base, contract_fingerprint('purchase', 'B', [{'role': 'buyer', 'companyId': 1}], {'q': 1}))
        self.assertNotEqual(
            base, contract_fingerprint('loan', 'A', [{'role': 'buyer', 'companyId': 1}], {'q': 1}))

    # ------------------------------------------------------------ 重导入

    def test_second_import_skips_duplicates(self):
        first = self._import()
        self.assertEqual(first['created'], 1)
        self.assertEqual(first['skipped'], 0)
        self.assertEqual(self._count(), 1)

        second = self._import()
        self.assertEqual(second['created'], 0)   # 重导入不再重复建
        self.assertEqual(second['skipped'], 1)
        self.assertTrue(any('已存在' in note for note in second['skipNotes']))
        self.assertEqual(self._count(), 1)
        # 比赛包不会新增公司，仍只有 setUp 里那一间
        ctx.set_competition_context(1, ALIAS)
        self.assertEqual(Company.objects.filter(name='买方公司').count(), 1)

    def test_duplicate_rows_inside_one_package_are_skipped(self):
        stats = self._import(rows=[self.rows[0], dict(self.rows[0])])
        self.assertEqual(stats['created'], 1)
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(self._count(), 1)

    def test_changed_inputs_create_a_new_contract(self):
        self._import()
        stats = self._import(rows=[{**self.rows[0], 'inputsJSON': '{"quantity": 99}'}])
        self.assertEqual(stats['created'], 1)      # 内容变了 → 视为新合同
        self.assertEqual(self._count(), 2)

    def test_renamed_contract_creates_a_new_contract(self):
        self._import()
        stats = self._import(rows=[{**self.rows[0], 'name': '改名后的采购'}])
        self.assertEqual(stats['created'], 1)
        self.assertEqual(self._count(), 2)

    def test_soft_deleted_contract_is_not_resurrected(self):
        self._import()
        ctx.set_competition_context(1, ALIAS)
        Contract.objects.update(deleted_at=timezone.now())
        stats = self._import()
        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(self._count(), 1)          # 仍只有那条已删除的合同

    def test_unknown_contract_type_still_reported_as_error(self):
        stats = self._import(rows=[{**self.rows[0], 'contractTypeKey': 'nope'}])
        self.assertEqual(stats['created'], 0)
        self.assertTrue(any('未知合同类型' in e for e in stats['errors']))
