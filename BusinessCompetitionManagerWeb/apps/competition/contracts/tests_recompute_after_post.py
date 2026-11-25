"""落账后公式重算（2026-11）：派生字段不再等财年定时器。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.global_.competitions.models import Competition
from plugins_runtime.api import Effect
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class _FakeModule:
    PARTY_ROLES = [{'role': 'buyer'}]
    INPUT_SCHEMA = [{'key': 'amount', 'label': '金额', 'type': 'NUMBER'}]

    @staticmethod
    def check(context):
        return []

    @staticmethod
    def apply(context):
        return [Effect(company='buyer', field='cash', op='ADD', value=100)]


class RecomputeAfterPostTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='公式重算赛', code='RCALC', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='公式公司')
        self.user = User.objects.create_user(
            username='recalc_user', password='x' * 12, email='recalc@test.local')

        IndustryField.objects.create(
            field_key='cash', name='现金', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        IndustryField.objects.create(
            field_key='loan_limit', name='贷款额度', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY, formula='cash * 0.5',
            is_calculated=True)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='cash', fiscal_year=None, value=100, version=1)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='loan_limit', fiscal_year=None, value=50, version=1)

    def _contract(self):
        return Contract.objects.create(
            contract_type_key='purchase', name='公式合同',
            status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'amount': 100}, unified_number='RCALC-FY0-00001',
            round_no=0, created_by=self.user.id)

    def test_formula_recomputed_right_after_posting(self):
        contract = self._contract()
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.execute_and_post(contract, operator=self.user)
        self.assertEqual(contract.status, Contract.Status.POSTED)

        cash = CompanyFieldValue.objects.get(
            company=self.company, field_key='cash', fiscal_year__isnull=True)
        loan_limit = CompanyFieldValue.objects.get(
            company=self.company, field_key='loan_limit', fiscal_year__isnull=True)
        self.assertEqual(float(cash.value), 200.0)
        # 不等定时器：落账当场重算
        self.assertEqual(float(loan_limit.value), 100.0)
        self.assertTrue(FieldLog.objects.filter(
            company=self.company, field_key='loan_limit',
            source=FieldLog.Source.CALC).exists())

    def test_calculated_field_not_touched_without_formula_change(self):
        contract = self._contract()
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.execute_and_post(contract, operator=self.user)
        # 再落一次补录（历史账）不触发重算，值保持不变
        self.assertEqual(float(CompanyFieldValue.objects.get(
            company=self.company, field_key='loan_limit',
            fiscal_year__isnull=True).value), 100.0)
