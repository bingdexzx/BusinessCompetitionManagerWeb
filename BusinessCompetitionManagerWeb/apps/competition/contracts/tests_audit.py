"""合同审计信息可见性：确认时间线 / 检查记录 / 效果审计 / 资金账本链只给超级管理员。

这些内容含重演值、检查依据与跨公司资金流，参赛代表（含队长）与主席团一律不可见。
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
from apps.global_.teams.models import Team, TeamMember
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
        self.assertIn('管理员', resp.json()['message'])

    def test_committee_admin_cannot_see_other_companies_contract(self):
        """主席团只辖别的公司 → 本合同对他不可见（404，连链都拿不到）。"""
        other = Company.objects.create(name='别人的公司')
        admin = self._user('lg_admin', CompetitionMembership.Identity.ADMIN)
        admin_membership = CompetitionMembership.objects.get(user=admin)
        admin_membership.managed_companies = [other.id]
        admin_membership.save(update_fields=['managed_companies'])
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    def test_committee_admin_sees_own_company_chain(self):
        admin = self._user('lg_admin2', CompetitionMembership.Identity.ADMIN)
        admin_membership = CompetitionMembership.objects.get(user=admin)
        admin_membership.managed_companies = [self.company.id]
        admin_membership.save(update_fields=['managed_companies'])
        self.client.force_authenticate(admin)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content)
        chains = resp.json()['chains']
        self.assertEqual([c['companyId'] for c in chains], [self.company.id])

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


class ContractAuditVisibilityTests(TestCase):
    """合同详情：时间线/检查记录只对超管返回；效果审计接口也只对超管开放。"""

    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='合同审计可见性赛', code='CAUDIT', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.client = APIClient()

        self.company = Company.objects.create(name='审计公司')
        self.contract = Contract.objects.create(
            contract_type_key='PO', name='审计合同', status=Contract.Status.POSTED,
            parties=[{'role': 'BUYER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'quantity': 3}, unified_number='PO-A-FY1-0001', round_no=1, created_by=1)
        ContractFieldEffect.objects.create(
            contract=self.contract, company=self.company, field_key='cash',
            op=ContractFieldEffect.Op.ADD, value_raw=50,
            before_raw=100, after_raw=150, round_no=1)
        CompanyFieldValue.objects.update_or_create(
            company=self.company, field_key='cash', fiscal_year=None,
            defaults={'value': 150, 'version': 1})

        self.player = self._user('aud_player', CompetitionMembership.Identity.PLAYER)
        team = Team.objects.create(
            competition=self.competition, name='审计队', captain=self.player,
            company_id=self.company.id)
        TeamMember.objects.create(team=team, user=self.player, role=TeamMember.Role.CAPTAIN)

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

    def _detail_url(self) -> str:
        return f'/api/competitions/{self.cid}/contracts/{self.contract.id}'

    def _effects_url(self) -> str:
        return f'{self._detail_url()}/effects'

    def test_player_detail_omits_timeline_and_checks(self):
        self.client.force_authenticate(self.player)
        resp = self.client.get(self._detail_url())
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertNotIn('timeline', body)
        self.assertNotIn('checks', body)
        # 合同本身对当事方仍可见（输入项/参与方/状态都在）
        self.assertIn('inputs', body)
        self.assertIn('parties', body)
        self.assertEqual(body['status'], Contract.Status.POSTED)

    def test_super_admin_detail_includes_timeline_and_checks(self):
        comp_admin = self._user('aud_comp', CompetitionMembership.Identity.COMP_SUPER_ADMIN)
        self.client.force_authenticate(comp_admin)
        body = self.client.get(self._detail_url()).json()
        self.assertIn('timeline', body)
        self.assertIn('checks', body)

    def test_player_cannot_read_effects(self):
        self.client.force_authenticate(self.player)
        resp = self.client.get(self._effects_url())
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_committee_admin_sees_managed_company_audit(self):
        """主席团管辖本合同的公司 → 能看到时间线/检查记录与效果审计。"""
        admin = self._user('aud_admin', CompetitionMembership.Identity.ADMIN)
        membership = CompetitionMembership.objects.get(user=admin)
        membership.managed_companies = [self.company.id]
        membership.save(update_fields=['managed_companies'])

        self.client.force_authenticate(admin)
        body = self.client.get(self._detail_url()).json()
        self.assertIn('timeline', body)
        self.assertIn('checks', body)

        effects = self.client.get(self._effects_url())
        self.assertEqual(effects.status_code, 200, effects.content)
        self.assertEqual([row['companyId'] for row in effects.json()], [self.company.id])

    def test_committee_admin_without_managed_party_gets_no_audit(self):
        """主席团只管别的公司（这里靠队伍身份才看得见合同）→ 不下发审计信息。"""
        other = Company.objects.create(name='别家公司')
        admin = self._user('aud_admin2', CompetitionMembership.Identity.ADMIN)
        membership = CompetitionMembership.objects.get(user=admin)
        membership.managed_companies = [other.id]
        membership.save(update_fields=['managed_companies'])
        TeamMember.objects.create(team=Team.objects.get(name='审计队'), user=admin,
                                  role=TeamMember.Role.MEMBER)

        self.client.force_authenticate(admin)
        body = self.client.get(self._detail_url()).json()
        self.assertNotIn('timeline', body)
        self.assertNotIn('checks', body)
        self.assertEqual(self.client.get(self._effects_url()).json(), [])

    def test_comp_super_admin_can_read_effects(self):
        comp_admin = self._user('aud_comp2', CompetitionMembership.Identity.COMP_SUPER_ADMIN)
        self.client.force_authenticate(comp_admin)
        resp = self.client.get(self._effects_url())
        self.assertEqual(resp.status_code, 200, resp.content)

