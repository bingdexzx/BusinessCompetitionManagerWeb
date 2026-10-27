"""资金账本链（重演）权限：只有系统超管 / 比赛超管可读。

链路含跨公司资金流与重算依据，参赛代表（含队长）与主席团一律不可见。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.industries.models import CompanyFieldValue
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class ContractLedgerPermissionTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='账本权限测试赛', code='LEDGER', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.client = APIClient()

        self.company = Company.objects.create(name='账本公司')
        self.contract = Contract.objects.create(
            contract_type_key='PO', name='账本测试合同', status=Contract.Status.DRAFT,
            parties=[{'role': 'BUYER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='PO-L-FY1-0001', round_no=1, created_by=1)
        ContractFieldEffect.objects.create(
            contract=self.contract, company=self.company, field_key='cash',
            op=ContractFieldEffect.Op.ADD, value_raw=50,
            before_raw=100, after_raw=150, round_no=1)
        CompanyFieldValue.objects.update_or_create(
            company=self.company, field_key='cash', fiscal_year=None,
            defaults={'value': 150, 'version': 1})

    def _url(self) -> str:
        return f'/api/competitions/{self.cid}/contracts/{self.contract.id}/ledger'

    def _user(self, name: str, identity: str | None = None, *, superuser: bool = False):
        user = User.objects.create_user(
            username=name, password='x' * 12, email=f'{name}@test.local')
        if superuser:
            user.is_superuser = True
            user.is_staff = True
            user.save(update_fields=['is_superuser', 'is_staff'])
        if identity:
            CompetitionMembership.objects.create(
                user=user, competition=self.competition, identity=identity)
        return user

    def test_player_cannot_read_ledger(self):
        player = self._user('lg_player', CompetitionMembership.Identity.PLAYER)
        self.client.force_authenticate(player)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn('超级管理员', resp.json()['message'])

    def test_committee_admin_cannot_read_ledger(self):
        admin = self._user('lg_admin', CompetitionMembership.Identity.ADMIN)
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_competition_super_admin_can_read_ledger(self):
        comp_admin = self._user('lg_comp', CompetitionMembership.Identity.COMP_SUPER_ADMIN)
        self.client.force_authenticate(comp_admin)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('chains', resp.json())

    def test_system_superuser_can_read_ledger(self):
        root = self._user('lg_root', superuser=True)
        self.client.force_authenticate(root)
        self.assertEqual(self.client.get(self._url()).status_code, 200)
