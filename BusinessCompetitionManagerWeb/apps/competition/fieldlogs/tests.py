"""字段日志权限：只有系统超级管理员 / 比赛超级管理员能看（2026-10 决策）。

字段级流水会暴露各公司成本、利润等敏感数据，参赛代表（含队长）与主席团一律不可见。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class FieldLogPermissionTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='字段日志权限赛', code='FIELDLOG', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.client = APIClient()

    def _url(self, suffix: str = '') -> str:
        return f'/api/competitions/{self.cid}/logs/fields{suffix}'

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

    def test_player_cannot_read_field_logs(self):
        player = self._user('fl_player', CompetitionMembership.Identity.PLAYER)
        self.client.force_authenticate(player)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_player_cannot_export_field_logs(self):
        player = self._user('fl_player2', CompetitionMembership.Identity.PLAYER)
        self.client.force_authenticate(player)
        self.assertEqual(self.client.post(self._url('/export'), {}, format='json').status_code, 403)

    def test_system_superuser_can_read_and_export(self):
        root = self._user('fl_root', superuser=True)
        self.client.force_authenticate(root)
        self.assertEqual(self.client.get(self._url()).status_code, 200)
        self.assertEqual(self.client.post(self._url('/export'), {}, format='json').status_code, 200)

    def test_outsider_cannot_read(self):
        outsider = self._user('fl_outsider')
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self._url()).status_code, 403)
