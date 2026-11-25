"""冻结超时、股票写入守卫、插件异常包装（2026-11）。"""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.competition.ledger.models import ContractFreeze
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class _BoomModule:
    PARTY_ROLES = []
    INPUT_SCHEMA = []

    @staticmethod
    def check(context):
        raise ZeroDivisionError('boom-check')

    @staticmethod
    def apply(context):
        raise KeyError('boom-apply')


class _OkModule:
    PARTY_ROLES = []
    INPUT_SCHEMA = []

    @staticmethod
    def check(context):
        return []

    @staticmethod
    def apply(context):
        return []


class FreezeAndPluginTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='冻结超时赛', code='FRZ', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='冻结公司')
        self.user = User.objects.create_user(
            username='frz_user', password='x' * 12, email='frz@test.local')
        self.contract = Contract.objects.create(
            contract_type_key='purchase', name='冻结合同',
            status=Contract.Status.MOD_EDITING,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='FRZ-FY0-00001', round_no=1,
            created_by=self.user.id)

    def _freeze(self, hours_ago: float):
        freeze = ContractFreeze.objects.create(
            contract=self.contract, company=self.company,
            field_key=engine.ALL_FIELDS, reason='修改中')
        frozen_at = timezone.now() - timedelta(hours=hours_ago)
        ContractFreeze.objects.filter(pk=freeze.pk).update(frozen_at=frozen_at)
        return freeze

    def test_fresh_freeze_blocks_field_write(self):
        self._freeze(hours_ago=1)
        with self.assertRaises(engine.ContractError):
            engine.assert_field_writable(self.company.id, 'cash')

    def test_stale_freeze_auto_expires(self):
        self._freeze(hours_ago=engine.FREEZE_TIMEOUT_HOURS + 1)
        engine.assert_field_writable(self.company.id, 'cash')  # 不抛异常
        freeze = ContractFreeze.objects.get(contract=self.contract)
        self.assertIsNotNone(freeze.unfrozen_at)
        self.assertIn('自动解冻', freeze.reason)

    def test_stale_freeze_does_not_block_execution(self):
        self._freeze(hours_ago=engine.FREEZE_TIMEOUT_HOURS + 1)
        other = Contract.objects.create(
            contract_type_key='purchase', name='另一张合同',
            status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='FRZ-FY0-00002', round_no=0,
            created_by=self.user.id)
        with mock.patch.object(engine, 'load_contract_module', return_value=_OkModule):
            engine.execute_and_post(other, operator=self.user)
        self.assertEqual(other.status, Contract.Status.POSTED)

    def test_plugin_exception_becomes_business_error(self):
        draft = Contract.objects.create(
            contract_type_key='purchase', name='插件异常草稿',
            status=Contract.Status.DRAFT,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='', round_no=0, created_by=self.user.id)
        with mock.patch.object(engine, 'load_contract_module', return_value=_BoomModule):
            with self.assertRaises(engine.ContractError) as caught:
                engine.submit_contract(draft, user=self.user)
        self.assertIn('插件执行失败', str(caught.exception))

    def test_plugin_apply_exception_becomes_business_error(self):
        contract = Contract.objects.create(
            contract_type_key='purchase', name='异常合同',
            status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='FRZ-FY0-00003', round_no=0,
            created_by=self.user.id)
        with mock.patch.object(engine, 'load_contract_module', return_value=_BoomModule):
            with self.assertRaises(engine.ContractError) as caught:
                engine.execute_and_post(contract, operator=self.user)
        self.assertIn('插件执行失败', str(caught.exception))
