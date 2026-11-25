"""审批超时提醒（2026-11）：超过 24h 未处理 → 催办超管与申请方，且只催一次。"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract, ContractModRequest
from apps.competition.contracts.presenters import _contract_data
from apps.global_.competitions.models import Competition
from apps.global_.messages.models import Message
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class OverdueReviewTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='超时提醒赛', code='OVD', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='超时公司')
        self.root = User.objects.create_user(
            username='ovd_root', password='x' * 12, email='ovd_root@test.local',
            is_superuser=True)
        self.applicant = User.objects.create_user(
            username='ovd_applicant', password='x' * 12, email='ovd_applicant@test.local')

    def _contract(self, status='MOD_APPLYING', hours_ago=25, with_mod=True):
        contract = Contract.objects.create(
            contract_type_key='purchase', name='超时合同', status=status,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='OVD-FY0-00001', round_no=1,
            created_by=self.applicant.id)
        if with_mod and status == 'MOD_APPLYING':
            ContractModRequest.objects.create(
                contract=contract, requested_by=self.applicant.id,
                requested_by_username=self.applicant.username, reason='改一下',
                status=ContractModRequest.Status.APPLYING)
        old = timezone.now() - timedelta(hours=hours_ago)
        Contract.objects.filter(pk=contract.pk).update(updated_at=old)
        contract.refresh_from_db()
        return contract

    def _messages(self, kind):
        return Message.objects.using('default').filter(
            payload__noticeKind=kind, competition_id=self.cid)

    def test_fresh_pending_is_not_overdue(self):
        contract = self._contract(hours_ago=1)
        self.assertFalse(engine.is_overdue(contract))

    def test_old_pending_is_overdue(self):
        contract = self._contract(hours_ago=25)
        self.assertTrue(engine.is_overdue(contract))
        ctx.set_competition_context(self.cid, ALIAS)
        data = _contract_data(contract)
        self.assertTrue(data['overdue'])

    def test_other_status_never_overdue(self):
        contract = self._contract(status='POSTED', hours_ago=48, with_mod=False)
        self.assertFalse(engine.is_overdue(contract))

    def test_notify_sends_to_superadmin_and_applicant_once(self):
        contract = self._contract(hours_ago=30)
        sent = engine.notify_overdue(contract)
        self.assertGreaterEqual(sent, 1)
        self.assertEqual(self._messages('CONTRACT_OVERDUE').count(), 1)
        self.assertEqual(self._messages('CONTRACT_OVERDUE_WAIT').count(), 1)

        # 第二次不再重复提醒
        self.assertEqual(engine.notify_overdue(contract), 0)
        self.assertEqual(self._messages('CONTRACT_OVERDUE').count(), 1)

    def test_notify_skips_fresh(self):
        contract = self._contract(hours_ago=2)
        self.assertEqual(engine.notify_overdue(contract), 0)
        self.assertEqual(self._messages('CONTRACT_OVERDUE').count(), 0)
