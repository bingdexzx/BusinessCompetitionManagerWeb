"""纪念票：加入比赛生成快照 + /api/me/tickets 返回。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.global_.competitions.models import Competition
from apps.global_.invites.models import InviteCode
from apps.global_.memberships.models import CompetitionMembership

User = get_user_model()


class JoinTicketSnapshotTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.competition = Competition.objects.create(
            name='纪念票测试赛', code='TICKET', ticket_image='/media/ticket.png')
        self.invite = InviteCode.objects.create(
            code='TICKET-CODE', competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER,
            max_uses=5, created_by=1,
        )
        self.user = User.objects.create_user(
            username='ticket_user', password='x' * 12, email='ticket@test.local',
            display_name='票面持有人')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_redeem_captures_ticket_snapshot(self):
        response = self.client.post('/api/invites/redeem', {'code': 'TICKET-CODE'},
                                   format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 201, response.content)

        membership = CompetitionMembership.objects.get(
            user=self.user, competition=self.competition)
        snapshot = membership.ticket_snapshot
        self.assertEqual(snapshot['competitionName'], '纪念票测试赛')
        self.assertEqual(snapshot['ticketNo'], membership.ticket_no)
        self.assertEqual(snapshot['ticketImage'], '/media/ticket.png')
        self.assertEqual(snapshot['userName'], '票面持有人')
        self.assertEqual(snapshot['identityLabel'], '参赛代表')
        self.assertIn('joinedAt', snapshot)

    def test_my_tickets_returns_snapshot(self):
        self.client.post('/api/invites/redeem', {'code': 'TICKET-CODE'},
                         format='json', HTTP_HOST='127.0.0.1')
        response = self.client.get('/api/me/tickets', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['competitionName'], '纪念票测试赛')
        self.assertEqual(rows[0]['ticketImage'], '/media/ticket.png')
        self.assertTrue(rows[0]['ticketNo'])

    def test_my_tickets_falls_back_for_legacy_membership(self):
        CompetitionMembership.objects.create(
            user=self.user, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        response = self.client.get('/api/me/tickets', HTTP_HOST='127.0.0.1')
        rows = response.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['competitionName'], '纪念票测试赛')
        self.assertTrue(rows[0]['ticketNo'])

    def test_holder_uses_display_name(self):
        self.user.display_name = '张三'
        self.user.save(update_fields=['display_name'])
        CompetitionMembership.objects.create(
            user=self.user, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        response = self.client.get('/api/me/tickets', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.json()[0]['userName'], '张三')

    def test_holder_falls_back_to_username_and_tracks_rename(self):
        self.user.display_name = ''
        self.user.save(update_fields=['display_name'])
        CompetitionMembership.objects.create(
            user=self.user, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        rows = self.client.get('/api/me/tickets', HTTP_HOST='127.0.0.1').json()
        self.assertEqual(rows[0]['userName'], self.user.username)

        self.user.display_name = '李四'
        self.user.save(update_fields=['display_name'])
        rows = self.client.get('/api/me/tickets', HTTP_HOST='127.0.0.1').json()
        self.assertEqual(rows[0]['userName'], '李四')

    def test_competition_rename_does_not_change_snapshot(self):
        self.client.post('/api/invites/redeem', {'code': 'TICKET-CODE'},
                         format='json', HTTP_HOST='127.0.0.1')
        self.competition.name = '改名后的比赛'
        self.competition.save(update_fields=['name'])

        response = self.client.get('/api/me/tickets', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.json()[0]['competitionName'], '纪念票测试赛')
