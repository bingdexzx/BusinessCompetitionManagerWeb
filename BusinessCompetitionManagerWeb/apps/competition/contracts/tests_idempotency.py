"""合同状态机幂等（2026-11）：重复点击 / 并发重入时不允许二次推进或二次落账。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import (
    Contract, ContractConfirmation, ContractFieldEffect, ContractModRequest,
)
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
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
        return [Effect(company='buyer', field='cash', op='ADD', value=5)]


class ContractIdempotencyTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='幂等测试赛', code='IDEM', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.company = Company.objects.create(name='幂等公司')
        self.user = User.objects.create_user(
            username='idem_user', password='x' * 12, email='idem@test.local')
        CompetitionMembership.objects.create(
            user=self.user, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN,
            managed_companies=[self.company.id])

    def _contract(self, status, **kwargs):
        defaults = dict(
            contract_type_key='purchase', name='幂等合同', status=status,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'amount': 1}, unified_number='IDEM-FY0-00001',
            round_no=0, created_by=self.user.id,
        )
        defaults.update(kwargs)
        return Contract.objects.create(**defaults)

    def test_confirm_twice_only_advances_once(self):
        contract = self._contract(Contract.Status.PENDING_PARTY)
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.confirm_party(contract, user=self.user)
            self.assertEqual(contract.status, Contract.Status.POSTED)
            # 第二次点击：状态已不在待确认，直接拒绝
            with self.assertRaises(engine.ContractError):
                engine.confirm_party(contract, user=self.user)
        self.assertEqual(ContractConfirmation.objects.filter(contract=contract).count(), 1)
        self.assertEqual(ContractFieldEffect.objects.filter(contract=contract).count(), 1)

    def test_execute_twice_posts_once(self):
        contract = self._contract(Contract.Status.PENDING_EXEC, round_no=0)
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.execute_and_post(contract, operator=self.user)
            self.assertEqual(contract.status, Contract.Status.POSTED)
            with self.assertRaises(engine.ContractError) as caught:
                engine.execute_and_post(contract, operator=self.user)
        self.assertIn('不允许执行', str(caught.exception))
        self.assertEqual(ContractFieldEffect.objects.filter(contract=contract).count(), 1)

    def test_submit_twice_rejected(self):
        contract = self._contract(Contract.Status.DRAFT)
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.submit_contract(contract, user=self.user)
            self.assertEqual(contract.status, Contract.Status.PENDING_PARTY)
            with self.assertRaises(engine.ContractError):
                engine.submit_contract(contract, user=self.user)

    def test_reject_twice_rejected(self):
        contract = self._contract(Contract.Status.PENDING_PARTY)
        engine.reject_party(contract, user=self.user, reason='不要了')
        self.assertEqual(contract.status, Contract.Status.DRAFT)
        with self.assertRaises(engine.ContractError):
            engine.reject_party(contract, user=self.user, reason='再来一次')

    def test_lock_refuses_deleted_contract(self):
        contract = self._contract(Contract.Status.DRAFT, deleted_at='2026-11-01T00:00:00Z')
        with self.assertRaises(engine.ContractError):
            engine.lock_contract(contract)

    def test_review_modify_twice_rejected(self):
        contract = self._contract(Contract.Status.MOD_APPLYING)
        ContractModRequest.objects.create(
            contract=contract, requested_by=self.user.id,
            requested_by_username='idem_user', reason='改一下',
            status=ContractModRequest.Status.APPLYING)
        engine.review_modify(contract, user=self.user, approve=True)
        self.assertEqual(contract.status, Contract.Status.MOD_EDITING)
        with self.assertRaises(engine.ContractError):
            engine.review_modify(contract, user=self.user, approve=True)
