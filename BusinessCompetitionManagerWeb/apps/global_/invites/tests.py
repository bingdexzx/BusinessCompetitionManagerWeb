"""激活码兑换：每人每场比赛只能激活一次（2026-11 决策）。

规则：同一个账号在同一场比赛里只能占用一个激活码名额，也只能有一个票据编号；
换一个激活码再兑换会被拒绝，且不会消耗新码的名额。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.global_.competitions.models import Competition
from apps.global_.invites.models import InviteCode, InviteRedemption
from apps.global_.memberships.models import CompetitionMembership

User = get_user_model()


class InviteRedeemOnceTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.competition = Competition.objects.create(
            name='激活一次测试赛', code='ONCE', db_name='comp_once_test')
        self.user = User.objects.create_user(username='once_player', password='x' * 12)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.first = InviteCode.objects.create(
            competition=self.competition, code='ONCE-A', identity='PLAYER', max_uses=5)
        self.second = InviteCode.objects.create(
            competition=self.competition, code='ONCE-B', identity='PLAYER', max_uses=5)

    def redeem(self, code):
        return self.client.post(
            '/api/invites/redeem', {'code': code}, format='json', HTTP_HOST='127.0.0.1')

    def test_second_activation_rejected_and_slot_not_consumed(self):
        first = self.redeem(self.first.code)
        self.assertEqual(first.status_code, 201)
        ticket_no = first.json()['ticketNo']
        self.assertIsNotNone(ticket_no)

        second = self.redeem(self.second.code)
        self.assertEqual(second.status_code, 400)
        self.assertIn('只能激活一次', second.json()['message'])

        # 只占一个名额、只有一条身份、一个票号
        self.second.refresh_from_db()
        self.assertEqual(self.second.used_count, 0)
        self.assertEqual(
            CompetitionMembership.objects.filter(
                user=self.user, competition=self.competition).count(), 1)
        membership = CompetitionMembership.objects.get(
            user=self.user, competition=self.competition)
        self.assertEqual(membership.ticket_no, ticket_no)
        self.assertEqual(InviteRedemption.objects.filter(user=self.user).count(), 1)

    def test_same_code_twice_rejected(self):
        self.assertEqual(self.redeem(self.first.code).status_code, 201)
        again = self.redeem(self.first.code)
        self.assertEqual(again.status_code, 400)
        self.first.refresh_from_db()
        self.assertEqual(self.first.used_count, 1)

    def test_other_competition_still_activatable(self):
        other = Competition.objects.create(
            name='另一场比赛', code='ONCE2', db_name='comp_once_test2')
        code = InviteCode.objects.create(
            competition=other, code='ONCE-C', identity='PLAYER', max_uses=1)
        self.assertEqual(self.redeem(self.first.code).status_code, 201)
        response = self.redeem(code.code)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            CompetitionMembership.objects.filter(
                user=self.user, competition=other).count(), 1)
