"""权限口径测试（2026-10 决策：分配公司后**队长可操作、队员只读**）。

- 可查看：``user_company_ids`` / ``can_view_company`` —— 队长与队员都能看本公司；
- 可操作：``user_operable_company_ids`` / ``can_act_for_company`` —— **仅队长**；
- 管理员按所辖公司、比赛超管/系统超管全部；
- 其他方表态（``company_strict_actor_ids``）同样收紧到队长。

公司 ID 只是队伍上的整数列，不触比赛库，故本测试只需默认库。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.common.authority import (
    can_act_for_company, can_view_company, company_strict_actor_ids,
    user_company_ids, user_operable_company_ids,
)
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.teams.models import Team, TeamMember

User = get_user_model()


class CompanyPermissionTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.competition = Competition.objects.create(name='权限赛', code='PERM')
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, None)  # 仅需要 competition_id

        self.captain = User.objects.create_user(
            username='cap', password='x' * 12, email='cap@test.local')
        self.mate = User.objects.create_user(
            username='mate', password='x' * 12, email='mate@test.local')
        self.other = User.objects.create_user(
            username='other', password='x' * 12, email='other@test.local')
        self.comp_admin = User.objects.create_user(
            username='cadmin', password='x' * 12, email='cadmin@test.local')
        self.sys_admin = User.objects.create_user(
            username='sadmin', password='x' * 12, email='sadmin@test.local', is_superuser=True)

        for user, identity in (
            (self.captain, CompetitionMembership.Identity.PLAYER),
            (self.mate, CompetitionMembership.Identity.PLAYER),
            (self.other, CompetitionMembership.Identity.PLAYER),
            (self.comp_admin, CompetitionMembership.Identity.COMP_SUPER_ADMIN),
        ):
            CompetitionMembership.objects.create(
                user=user, competition=self.competition, identity=identity)

        # 队长 captain 建队并任命；mate 入队；company_id=42
        self.team = Team.objects.create(
            competition=self.competition, name='甲队', captain=self.captain, company_id=42)
        TeamMember.objects.create(team=self.team, user=self.captain,
                                  role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=self.team, user=self.mate,
                                  role=TeamMember.Role.MEMBER)

    def tearDown(self):
        ctx.clear_request_context()

    # ------------------------------------------------------------ 可查看

    def test_captain_and_member_can_view_own_company(self):
        self.assertEqual(user_company_ids(self.captain, self.cid), {42})
        self.assertEqual(user_company_ids(self.mate, self.cid), {42})  # 队员可看
        self.assertTrue(can_view_company(self.captain, 42, self.cid))
        self.assertTrue(can_view_company(self.mate, 42, self.cid))
        self.assertFalse(can_view_company(self.other, 42, self.cid))

    def test_super_admin_and_comp_admin_view_all(self):
        self.assertEqual(user_company_ids(self.sys_admin, self.cid), {'*'})
        self.assertEqual(user_company_ids(self.comp_admin, self.cid), {'*'})

    # ------------------------------------------------------------ 可操作

    def test_only_captain_can_operate(self):
        self.assertEqual(user_operable_company_ids(self.captain, self.cid), {42})
        # 队员只读：可操作集合为空
        self.assertEqual(user_operable_company_ids(self.mate, self.cid), set())
        self.assertTrue(can_act_for_company(self.captain, 42, self.cid))
        self.assertFalse(can_act_for_company(self.mate, 42, self.cid))
        self.assertFalse(can_act_for_company(self.other, 42, self.cid))

    def test_super_admin_and_comp_admin_can_operate(self):
        self.assertEqual(user_operable_company_ids(self.sys_admin, self.cid), {'*'})
        self.assertEqual(user_operable_company_ids(self.comp_admin, self.cid), {'*'})
        self.assertTrue(can_act_for_company(self.sys_admin, 999, self.cid))
        self.assertTrue(can_act_for_company(self.comp_admin, 999, self.cid))

    def test_admin_operates_managed_companies(self):
        admin = User.objects.create_user(
            username='mgr', password='x' * 12, email='mgr@test.local')
        CompetitionMembership.objects.create(
            user=admin, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN, managed_companies=[42, 7])
        self.assertEqual(user_operable_company_ids(admin, self.cid), {42, 7})
        self.assertEqual(user_company_ids(admin, self.cid), {42, 7})
        self.assertTrue(can_act_for_company(admin, 7, self.cid))

    def test_no_membership_has_no_access(self):
        stranger = User.objects.create_user(
            username='stranger', password='x' * 12, email='stranger@test.local')
        self.assertEqual(user_company_ids(stranger, self.cid), set())
        self.assertEqual(user_operable_company_ids(stranger, self.cid), set())

    # ------------------------------------------------------------ 管理员兼任队长/队员

    def _admin(self, name: str, managed=None):
        user = User.objects.create_user(
            username=name, password='x' * 12, email=f'{name}@test.local')
        CompetitionMembership.objects.create(
            user=user, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN, managed_companies=managed or [])
        return user

    def test_admin_as_captain_operates_own_team_company(self):
        """主席团成员兼任队长：所辖公司 ∪ 本队公司（否则"既当裁判又参赛"的人操作不了自己公司）。"""
        admin = self._admin('admin_cap', managed=[])
        TeamMember.objects.create(team=self.team, user=admin, role=TeamMember.Role.MEMBER)
        self.team.captain = admin
        self.team.save(update_fields=['captain'])

        self.assertEqual(user_company_ids(admin, self.cid), {42})
        self.assertEqual(user_operable_company_ids(admin, self.cid), {42})

    def test_admin_as_member_views_but_not_operates_team_company(self):
        admin = self._admin('admin_mate', managed=[7])
        TeamMember.objects.create(team=self.team, user=admin, role=TeamMember.Role.MEMBER)

        # 可查看：所辖 7 ∪ 本队 42；可操作：只有所辖 7（队员只读）
        self.assertEqual(user_company_ids(admin, self.cid), {42, 7})
        self.assertEqual(user_operable_company_ids(admin, self.cid), {7})

    # ------------------------------------------------------------ 表态（其他方确认）

    def test_strict_actor_ids_is_captain_only(self):
        """其他方表态按公司计票：只认队长 + 所辖管理员，队员与超管都不自动代表态。"""
        ids = company_strict_actor_ids(42)
        self.assertIn(self.captain.id, ids)
        self.assertNotIn(self.mate.id, ids)        # 队员只读
        self.assertNotIn(self.comp_admin.id, ids)  # 比赛超管不自动投票
        self.assertNotIn(self.sys_admin.id, ids)
