"""工具箱计时器 API 测试（比赛域多库路由）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.tools.models import CompetitionTimer
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class CompetitionTimerApiTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='计时器赛', code='TMR', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.player = get_user_model().objects.create_user(
            username='timer_player', password='x' * 12, email='tmr@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client = APIClient()
        self.client.force_authenticate(self.player)

    def _url(self, suffix: str = '') -> str:
        return f'/api/competitions/{self.cid}/timers{suffix}'

    def test_create_and_list_timer(self):
        resp = self.client.post(self._url(), {
            'name': '第一轮结算倒计时',
            'durationSeconds': 3600,
            'note': '准时提交',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['name'], '第一轮结算倒计时')
        self.assertEqual(resp.data['durationSeconds'], 3600)
        self.assertLessEqual(resp.data['remainingSeconds'], 3600)
        self.assertGreater(resp.data['remainingSeconds'], 3500)
        self.assertEqual(resp.data['createdByUsername'], 'timer_player')

        listed = self.client.get(self._url())
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data['items']), 1)
        self.assertEqual(listed.data['items'][0]['note'], '准时提交')

    def test_name_and_duration_required(self):
        missing_name = self.client.post(
            self._url(), {'durationSeconds': 60}, format='json')
        self.assertEqual(missing_name.status_code, 400)
        self.assertIn('名称', missing_name.data['message'])

        bad_duration = self.client.post(
            self._url(), {'name': '坏时长', 'durationSeconds': 0}, format='json')
        self.assertEqual(bad_duration.status_code, 400)
        self.assertIn('时长', bad_duration.data['message'])

        too_long = self.client.post(
            self._url(), {'name': '太久', 'durationSeconds': 31 * 24 * 3600}, format='json')
        self.assertEqual(too_long.status_code, 400)

    def test_update_and_delete_timer(self):
        created = self.client.post(self._url(), {
            'name': '旧名称', 'durationSeconds': 600,
        }, format='json').data
        updated = self.client.patch(self._url(f'/{created["id"]}'), {
            'name': '新名称', 'durationSeconds': 120,
        }, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.data['name'], '新名称')
        self.assertEqual(updated.data['durationSeconds'], 120)
        self.assertLessEqual(updated.data['remainingSeconds'], 120)

        removed = self.client.delete(self._url(f'/{created["id"]}'))
        self.assertEqual(removed.status_code, 204)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(CompetitionTimer.objects.count(), 0)

    def test_unknown_timer_returns_404(self):
        self.assertEqual(self.client.delete(self._url('/999999')).status_code, 404)

    def test_timers_are_isolated_per_user(self):
        # 玩家自己的计时器
        mine = self.client.post(self._url(), {
            'name': '我的倒计时', 'durationSeconds': 600,
        }, format='json').data

        # 同比赛的另一个成员：看不到我的、也删不掉我的
        teammate = get_user_model().objects.create_user(
            username='teammate', password='x' * 12, email='mate@test.local')
        CompetitionMembership.objects.create(
            user=teammate, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        other_client = APIClient()
        other_client.force_authenticate(teammate)

        self.assertEqual(other_client.get(self._url()).data['items'], [])
        self.assertEqual(
            other_client.delete(self._url(f'/{mine["id"]}')).status_code, 404)
        self.assertEqual(
            other_client.patch(
                self._url(f'/{mine["id"]}'), {'name': '改别人'}, format='json'
            ).status_code,
            404,
        )

        # 自己还是能看到并管理
        self.assertEqual(len(self.client.get(self._url()).data['items']), 1)
        self.assertEqual(
            self.client.delete(self._url(f'/{mine["id"]}')).status_code, 204)

    def test_outsider_forbidden(self):
        outsider = get_user_model().objects.create_user(
            username='outsider', password='x' * 12, email='out@test.local')
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self._url()).status_code, 403)
        self.assertEqual(
            self.client.post(self._url(), {
                'name': 'x', 'durationSeconds': 60,
            }, format='json').status_code,
            403,
        )
