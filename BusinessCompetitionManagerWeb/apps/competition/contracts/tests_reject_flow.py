"""拒绝确认与草稿编辑（2026-11 决策）：待确认合同任一方可拒绝 → 退回草稿，可改后重提。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.teams.models import Team
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class _FakeModule:
    PARTY_ROLES = [{'role': 'buyer'}, {'role': 'seller'}]
    INPUT_SCHEMA = [{'key': 'quantity', 'label': '数量', 'type': 'NUMBER'}]


class RejectFlowTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='拒绝确认测试赛', code='REJ', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.buyer = Company.objects.create(name='买方公司')
        self.seller = Company.objects.create(name='卖方公司')
        self.buyer_captain = self._captain('rej_buyer', self.buyer)
        self.outsider = User.objects.create_user(
            username='rej_outsider', password='x' * 12, email='rej_outsider@test.local')

        self.contract = Contract.objects.create(
            contract_type_key='purchase', name='拒绝测试合同',
            status=Contract.Status.PENDING_PARTY,
            parties=[
                {'role': 'buyer', 'companyId': self.buyer.id, 'confirmOrder': 0,
                 'confirmAt': timezone.now().isoformat(), 'confirmedBy': 'rej_buyer'},
                {'role': 'seller', 'companyId': self.seller.id, 'confirmOrder': 1},
            ],
            inputs={'quantity': 3}, unified_number='', round_no=0,
            created_by=self.buyer_captain.id,
        )

    def _captain(self, username, company):
        user = User.objects.create_user(
            username=username, password='x' * 12, email=f'{username}@test.local')
        CompetitionMembership.objects.create(
            user=user, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        Team.objects.create(
            name=f'{username}队', competition=self.competition,
            captain=user, company_id=company.id)
        return user

    def test_reject_returns_to_draft_and_clears_chain(self):
        engine.reject_party(self.contract, user=self.buyer_captain, reason='价格不对')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.DRAFT)
        self.assertEqual(self.contract.pending_party_index, 0)
        buyer = next(p for p in self.contract.parties if p['role'] == 'buyer')
        self.assertNotIn('confirmAt', buyer)
        self.assertNotIn('confirmedBy', buyer)
        self.assertEqual(buyer['rejectedBy'], 'rej_buyer')
        self.assertEqual(buyer['rejectReason'], '价格不对')
        self.assertTrue(buyer['rejectedAt'])

    def test_reject_requires_pending_party_status(self):
        self.contract.status = Contract.Status.DRAFT
        self.contract.save(update_fields=['status'])
        with self.assertRaises(engine.ContractError):
            engine.reject_party(self.contract, user=self.buyer_captain)

    def test_reject_rejected_for_outsider(self):
        with self.assertRaises(engine.ContractPermissionError):
            engine.reject_party(self.contract, user=self.outsider)

    def test_draft_can_be_edited_after_reject(self):
        engine.reject_party(self.contract, user=self.buyer_captain, reason='数量要改')
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            engine.update_draft(self.contract, user=self.buyer_captain,
                                inputs={'quantity': 8})
            self.contract.refresh_from_db()
            self.assertEqual(self.contract.inputs, {'quantity': 8})
            buyer = next(p for p in self.contract.parties if p['role'] == 'buyer')
            self.assertNotIn('rejectedBy', buyer)

            with self.assertRaises(engine.ContractError):
                engine.update_draft(self.contract, user=self.buyer_captain, inputs={})

    def test_draft_edit_only_for_draft(self):
        with mock.patch.object(engine, 'load_contract_module', return_value=_FakeModule):
            with self.assertRaises(engine.ContractError):
                engine.update_draft(self.contract, user=self.buyer_captain,
                                    inputs={'quantity': 1})

    def test_pending_party_contract_can_be_deleted(self):
        root = User.objects.create_user(
            username='rej_root', password='x' * 12, email='rej_root@test.local',
            is_superuser=True)
        client = APIClient()
        client.force_authenticate(root)
        ctx.set_competition_context(self.cid, ALIAS)
        response = client.delete(
            f'/api/competitions/{self.cid}/contracts/{self.contract.id}',
            HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        ctx.set_competition_context(self.cid, ALIAS)
        self.contract.refresh_from_db()
        self.assertIsNotNone(self.contract.deleted_at)
