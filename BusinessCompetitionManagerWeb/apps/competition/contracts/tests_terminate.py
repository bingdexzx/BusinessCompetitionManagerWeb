"""合同终止（2026-11）：回滚当前轮次恢复字段值 → 置已终止 → 解冻 → 原因留痕。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.ledger.models import ContractFreeze
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from plugins_runtime.api import Effect
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class _FakeModule:
    PARTY_ROLES = [{'role': 'buyer'}]
    INPUT_SCHEMA = []

    @staticmethod
    def check(context):
        return []

    @staticmethod
    def apply(context):
        return [Effect(company='buyer', field='cash', op='ADD', value=50)]


class TerminateContractTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='终止测试赛', code='TERM', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='终止公司')
        self.user = User.objects.create_user(
            username='term_user', password='x' * 12, email='term@test.local')
        CompetitionMembership.objects.create(
            user=self.user, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN,
            managed_companies=[self.company.id])
        IndustryField.objects.create(
            field_key='cash', name='现金', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='cash', fiscal_year=None, value=100, version=1)

    def _posted_contract(self):
        contract = Contract.objects.create(
            contract_type_key='purchase', name='终止合同',
            status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='TERM-FY0-00001', round_no=0,
            created_by=self.user.id)
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.execute_and_post(contract, operator=self.user)
        return contract

    def test_terminate_posted_contract_rolls_back_values(self):
        contract = self._posted_contract()
        self.assertEqual(contract.status, Contract.Status.POSTED)
        cash = CompanyFieldValue.objects.get(
            company=self.company, field_key='cash', fiscal_year__isnull=True)
        self.assertEqual(float(cash.value), 150.0)

        engine.terminate_contract(contract, user=self.user, reason='比赛改规则')

        self.assertEqual(contract.status, Contract.Status.CANCELLED)
        self.assertEqual(contract.cancel_reason, '比赛改规则')
        self.assertEqual(contract.cancelled_by_username, 'term_user')
        self.assertIsNotNone(contract.cancelled_at)
        cash.refresh_from_db()
        self.assertEqual(float(cash.value), 100.0)   # 已回滚
        # 效果行保留（审计不可删）
        self.assertEqual(ContractFieldEffect.objects.filter(contract=contract).count(), 1)

    def test_terminate_releases_freeze(self):
        contract = self._posted_contract()
        ContractFreeze.objects.create(
            contract=contract, company=self.company, field_key=engine.ALL_FIELDS,
            reason='修改中')
        engine.terminate_contract(contract, user=self.user)
        freeze = ContractFreeze.objects.get(contract=contract)
        self.assertIsNotNone(freeze.unfrozen_at)

    def test_double_terminate_rejected(self):
        contract = self._posted_contract()
        engine.terminate_contract(contract, user=self.user)
        with self.assertRaises(engine.ContractError) as caught:
            engine.terminate_contract(contract, user=self.user)
        self.assertIn('已终止', str(caught.exception))

    def test_terminate_draft_contract(self):
        contract = Contract.objects.create(
            contract_type_key='purchase', name='草稿终止',
            status=Contract.Status.DRAFT,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='', round_no=0, created_by=self.user.id)
        engine.terminate_contract(contract, user=self.user, reason='不要了')
        self.assertEqual(contract.status, Contract.Status.CANCELLED)

    def test_terminate_tolerates_missing_creator(self):
        """历史导入合同的 created_by 可能是占位 ID：通知收件人要先过滤真实账号。"""
        contract = self._posted_contract()
        contract.created_by = 999999
        contract.save(update_fields=['created_by'])
        engine.terminate_contract(contract, user=self.user, reason='清理占位账号')
        self.assertEqual(contract.status, Contract.Status.CANCELLED)

    def test_terminated_contract_excluded_from_ledger_chain(self):
        from apps.competition.contracts import ledger

        contract = self._posted_contract()
        self.assertTrue(ledger.field_chain(self.company.id, 'cash')['nodes'])
        engine.terminate_contract(contract, user=self.user)
        # 终止后回滚了值，且合同不再是「生效」状态：链路仍保留审计（未软删），
        # 但当前值应等于回滚后的真实值
        chain = ledger.field_chain(self.company.id, 'cash')
        self.assertEqual(float(chain['currentValue']), 100.0)
