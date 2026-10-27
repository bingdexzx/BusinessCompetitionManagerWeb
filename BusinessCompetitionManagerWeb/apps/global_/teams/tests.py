"""队伍分配公司测试（2026-10 决策）。

管理员（系统超管 / 比赛超管）选产业 + 填公司名称 → 分配公司；
分配后**队长可操作、队员只读**（apps.common.authority）。

多库约定：比赛域模型走 comp_<id>；比赛库 alias 在导入期注册，URL 用 self.cid。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.common.authority import can_act_for_company, can_view_company
from apps.competition.companies.models import Company
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.packages.models import Package, PackagePlugin
from apps.global_.plugins.models import PluginRegistry
from apps.global_.teams.models import Team, TeamJoinCode, TeamMember
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class TeamCompanyAssignTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='分配公司测试赛', code='ASSIGN', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.manager = User.objects.create_user(
            username='assigner', password='x' * 12, email='assigner@test.local')
        CompetitionMembership.objects.create(
            user=self.manager, competition=self.competition,
            identity=CompetitionMembership.Identity.COMP_SUPER_ADMIN)
        self.captain = User.objects.create_user(
            username='tcap', password='x' * 12, email='tcap@test.local')
        self.mate = User.objects.create_user(
            username='tmate', password='x' * 12, email='tmate@test.local')
        for user in (self.captain, self.mate):
            CompetitionMembership.objects.create(
                user=user, competition=self.competition,
                identity=CompetitionMembership.Identity.PLAYER)

        self.team = Team.objects.create(
            competition=self.competition, name='甲队', captain=self.captain,
            industry_choice=['steel'])
        TeamMember.objects.create(team=self.team, user=self.captain,
                                  role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=self.team, user=self.mate,
                                  role=TeamMember.Role.MEMBER)

        # 已导入的产业插件（steel）：分配公司只允许选已导入的产业
        registry = PluginRegistry.objects.create(
            kind='INDUSTRY', key='steel', name='钢铁产业', version='1.0.0',
            sha256='a' * 64, file_name='industry_steel.py',
            file_path='plugins/steel/1.0.0/industry_steel.py')
        package = Package.objects.create(
            competition=self.competition, file_name='p.zip', file_path='packages/p.zip',
            sha256='b' * 64, status=Package.Status.SUCCESS)
        PackagePlugin.objects.create(
            package=package, plugin=registry, kind='INDUSTRY', key='steel', version='1.0.0')

        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    # ------------------------------------------------------------ 工具

    def _url(self, suffix: str) -> str:
        return f'/api/competitions/{self.cid}{suffix}'

    def _assign(self, **payload):
        body = {'industryKey': 'steel', 'companyName': '钢铁一号公司'}
        body.update(payload)
        return self.client.post(self._url(f'/teams/{self.team.id}/company'),
                                body, format='json')

    def _company(self, pk):
        ctx.set_competition_context(self.cid, ALIAS)
        return Company.objects.filter(pk=pk).first()

    # ------------------------------------------------------------ 分配

    def test_assign_creates_company_with_given_name(self):
        resp = self._assign()
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['companyName'], '钢铁一号公司')
        self.assertEqual(body['industryFinal'], 'steel')
        self.assertIsNotNone(body['companyId'])

        company = self._company(body['companyId'])
        self.assertEqual(company.name, '钢铁一号公司')  # 用输入的公司名，不是队伍名
        self.assertEqual(company.industry_key, 'steel')
        self.assertEqual(company.team_id, self.team.id)  # 一队一公司

        self.team.refresh_from_db()
        self.assertEqual(self.team.company_id, company.id)
        self.assertEqual(self.team.industry_final, 'steel')

    def test_assign_requires_industry_and_company_name(self):
        self.assertEqual(self._assign(industryKey='').status_code, 400)
        self.assertEqual(self._assign(companyName='   ').status_code, 400)
        self.assertEqual(self._assign(companyName='名' * 121).status_code, 400)
        self.assertEqual(self._assign(industryKey='', companyName='').status_code, 400)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(Company.objects.count(), 0)  # 校验失败不建公司

    def test_assign_rejects_unimported_industry(self):
        resp = self._assign(industryKey='auto')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('导入', resp.json()['message'])
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(Company.objects.count(), 0)

    def test_assign_requires_manager(self):
        self.client.force_authenticate(self.captain)  # 参赛代表不能给自己分配
        self.assertEqual(self._assign().status_code, 403)
        self.client.force_authenticate(self.mate)
        self.assertEqual(self._assign().status_code, 403)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(Company.objects.count(), 0)

    def test_reassign_updates_same_company(self):
        first = self._assign().json()
        resp = self._assign(companyName='钢铁二号公司')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['companyId'], first['companyId'])  # 同一公司行
        self.assertEqual(self._company(first['companyId']).name, '钢铁二号公司')
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(Company.objects.count(), 1)

    # ------------------------------------------------------------ 分配后的权限

    def test_captain_operates_member_reads(self):
        company_id = self._assign().json()['companyId']
        ctx.set_competition_context(self.cid, ALIAS)
        # 队长：可查看 + 可操作
        self.assertTrue(can_view_company(self.captain, company_id, self.cid))
        self.assertTrue(can_act_for_company(self.captain, company_id, self.cid))
        # 队员：可查看、不可操作
        self.assertTrue(can_view_company(self.mate, company_id, self.cid))
        self.assertFalse(can_act_for_company(self.mate, company_id, self.cid))

    def test_member_reads_company_table_but_cannot_edit(self):
        company_id = self._assign().json()['companyId']
        table_url = self._url(f'/companies/{company_id}/tables/entity')
        fields_url = self._url(f'/companies/{company_id}/fields')

        # 队员：可看表格
        self.client.force_authenticate(self.mate)
        self.assertEqual(self.client.get(table_url).status_code, 200)
        # 队员：不能改字段
        resp = self.client.patch(fields_url, {'fieldKey': 'cash', 'value': 1}, format='json')
        self.assertEqual(resp.status_code, 403)

        # 队长：可改字段
        self.client.force_authenticate(self.captain)
        resp = self.client.patch(fields_url, {'fieldKey': 'cash', 'value': 1}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_team_list_exposes_company_name(self):
        self._assign()
        resp = self.client.get(self._url('/teams'))
        self.assertEqual(resp.status_code, 200, resp.content)
        row = next(t for t in resp.json() if t['id'] == self.team.id)
        self.assertEqual(row['companyName'], '钢铁一号公司')

    # ------------------------------------------------------------ 产业下拉

    def test_industries_endpoint_lists_imported_ones(self):
        resp = self.client.get(self._url('/industries'))
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        self.assertEqual([r['key'] for r in rows], ['steel'])
        self.assertEqual(rows[0]['name'], '钢铁产业')

        # 参赛代表也能读（组队时填产业志愿要用）
        self.client.force_authenticate(self.captain)
        self.assertEqual(self.client.get(self._url('/industries')).status_code, 200)

    def test_industries_endpoint_denies_non_member(self):
        outsider = User.objects.create_user(
            username='outsider', password='x' * 12, email='outsider@test.local')
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self._url('/industries')).status_code, 403)


class TeamMembershipProvisionTests(TestCase):
    """组队前提：**已进入比赛**（有效成员身份）。

    队伍归属于比赛——没加入比赛就不能建队/进队，也不会被自动补成成员；
    未加入与被停用给出不同提示。
    """

    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='组队准入测试赛', code='TEAMGATE', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.client = APIClient()

    def _url(self, suffix: str) -> str:
        return f'/api/competitions/{self.cid}{suffix}'

    def _membership(self, user):
        return CompetitionMembership.objects.filter(
            user=user, competition=self.competition).first()

    def _user(self, name: str):
        return User.objects.create_user(
            username=name, password='x' * 12, email=f'{name}@test.local')

    def test_create_team_requires_joining_competition(self):
        """没进比赛不能建队，且**不会**被自动补成成员。"""
        user = self._user('newbie')
        self.client.force_authenticate(user)
        resp = self.client.post(self._url('/teams'), {'name': '新手队'}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn('请先加入本比赛', resp.json()['message'])
        self.assertFalse(Team.objects.filter(competition=self.competition).exists())
        self.assertIsNone(self._membership(user))  # 没有产生成员身份

    def test_join_team_requires_joining_competition(self):
        captain = self._user('gatecap')
        CompetitionMembership.objects.create(
            user=captain, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        team = Team.objects.create(
            competition=self.competition, name='老队', captain=captain)
        TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN)
        TeamJoinCode.objects.create(
            team=team, code='JOINME01', max_uses=1, created_by=captain.id,
            expires_at=timezone.now() + timezone.timedelta(days=1))

        joiner = self._user('joiner')
        self.client.force_authenticate(joiner)
        resp = self.client.post(self._url('/teams/join'), {'code': 'JOINME01'}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn('请先加入本比赛', resp.json()['message'])
        self.assertFalse(team.members.filter(user=joiner).exists())
        self.assertIsNone(self._membership(joiner))

    def test_inactive_membership_cannot_create_team(self):
        user = self._user('disabled')
        CompetitionMembership.objects.create(
            user=user, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER, is_active=False)
        self.client.force_authenticate(user)
        resp = self.client.post(self._url('/teams'), {'name': '被停用队'}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn('停用', resp.json()['message'])
        self.assertFalse(Team.objects.filter(competition=self.competition).exists())

    def test_joined_player_can_create_team(self):
        player = self._user('player')
        CompetitionMembership.objects.create(
            user=player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client.force_authenticate(player)
        resp = self.client.post(self._url('/teams'), {'name': '参赛队'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        team = Team.objects.get(competition=self.competition, name='参赛队')
        self.assertEqual(team.captain_id, player.id)
        self.assertEqual(self._membership(player).identity, CompetitionMembership.Identity.PLAYER)

    def test_admin_member_can_create_team_without_downgrade(self):
        """管理员已进入比赛时也能建队，身份保持 ADMIN（不被降级成 PLAYER）。"""
        admin = self._user('teamadmin')
        CompetitionMembership.objects.create(
            user=admin, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN, managed_companies=[999])
        self.client.force_authenticate(admin)
        resp = self.client.post(self._url('/teams'), {'name': '主席团队'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self._membership(admin).identity, CompetitionMembership.Identity.ADMIN)

