"""权限口径测试（2026-11 决策：取消比赛超级管理员，权限并入系统超级管理员；保留管理员/主席团按所辖公司）。

- 可查看：``user_company_ids`` / ``can_view_company`` —— 队长与队员都能看本公司；
  管理员另加所辖公司；系统超级管理员全部；
- 可操作：``user_operable_company_ids`` / ``can_act_for_company`` —— **仅队长**；
  管理员按所辖公司；系统超级管理员全部；
- 其他方表态（``company_strict_actor_ids``）收紧到队长 + 所辖管理员。

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
        self.admin = User.objects.create_user(
            username='cadmin', password='x' * 12, email='cadmin@test.local')
        self.sys_admin = User.objects.create_user(
            username='sadmin', password='x' * 12, email='sadmin@test.local', is_superuser=True)

        for user, identity in (
            (self.captain, CompetitionMembership.Identity.PLAYER),
            (self.mate, CompetitionMembership.Identity.PLAYER),
            (self.other, CompetitionMembership.Identity.PLAYER),
        ):
            CompetitionMembership.objects.create(
                user=user, competition=self.competition, identity=identity)
        # 管理员（主席团）：所辖 7 与 42
        CompetitionMembership.objects.create(
            user=self.admin, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN,
            managed_companies=[7, 42])

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

    def test_super_admin_view_all(self):
        self.assertEqual(user_company_ids(self.sys_admin, self.cid), {'*'})

    def test_admin_view_managed_companies(self):
        self.assertEqual(user_company_ids(self.admin, self.cid), {7, 42})
        self.assertTrue(can_view_company(self.admin, 7, self.cid))
        self.assertFalse(can_view_company(self.admin, 8, self.cid))

    # ------------------------------------------------------------ 可操作

    def test_only_captain_can_operate(self):
        self.assertEqual(user_operable_company_ids(self.captain, self.cid), {42})
        # 队员只读：可操作集合为空
        self.assertEqual(user_operable_company_ids(self.mate, self.cid), set())
        self.assertTrue(can_act_for_company(self.captain, 42, self.cid))
        self.assertFalse(can_act_for_company(self.mate, 42, self.cid))
        self.assertFalse(can_act_for_company(self.other, 42, self.cid))

    def test_super_admin_can_operate_all(self):
        self.assertEqual(user_operable_company_ids(self.sys_admin, self.cid), {'*'})
        self.assertTrue(can_act_for_company(self.sys_admin, 999, self.cid))

    def test_admin_operates_managed_companies(self):
        self.assertEqual(user_operable_company_ids(self.admin, self.cid), {7, 42})
        self.assertTrue(can_act_for_company(self.admin, 7, self.cid))
        self.assertFalse(can_act_for_company(self.admin, 8, self.cid))

    def test_no_membership_has_no_access(self):
        stranger = User.objects.create_user(
            username='stranger', password='x' * 12, email='stranger@test.local')
        self.assertEqual(user_company_ids(stranger, self.cid), set())
        self.assertEqual(user_operable_company_ids(stranger, self.cid), set())

    # ------------------------------------------------------------ 表态（其他方确认）

    def test_strict_actor_ids_includes_captain_and_managed_admin(self):
        """其他方表态按公司计票：队长与所辖管理员可表态，队员与系统超级管理员不自动代表态。"""
        ids = company_strict_actor_ids(42)
        self.assertIn(self.captain.id, ids)
        self.assertIn(self.admin.id, ids)          # 管理员辖 42
        self.assertNotIn(self.mate.id, ids)        # 队员只读
        self.assertNotIn(self.sys_admin.id, ids)
