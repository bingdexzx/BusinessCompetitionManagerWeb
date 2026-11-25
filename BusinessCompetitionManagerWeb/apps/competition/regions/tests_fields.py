"""区域字段（2026-11）：定义由比赛包提供（比赛级），值按区域存；超级管理员可手工改值。"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.regions.models import Region, RegionField
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class RegionFieldApiTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.competition = Competition.objects.create(
            name='区域字段赛', code='RF', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.region = Region.objects.create(name='华东')
        # 模拟比赛包导入后的定义（比赛级，与区域无关）
        self.field = RegionField.objects.create(
            field_key='market_capacity', name='市场容量',
            field_type=RegionField.FieldType.NUMBER, default_value=100,
            condition={'fieldKey': 'license', 'op': 'eq', 'value': True},
        )
        self.admin = get_user_model().objects.create_user(
            username='rf_admin', password='x' * 12, email='rf_admin@test.local',
            is_superuser=True)
        self.player = get_user_model().objects.create_user(
            username='rf_player', password='x' * 12, email='rf_player@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client = APIClient()

    def tearDown(self):
        ctx.clear_request_context()

    def _values_url(self, name: str | None = None) -> str:
        return (f'/api/competitions/{self.cid}/regions/by-name/'
                f'{name or self.region.name}/field-values')

    def test_definition_list(self):
        self.client.force_authenticate(self.player)
        resp = self.client.get(f'/api/competitions/{self.cid}/region-fields')
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['key'], 'market_capacity')
        self.assertEqual(rows[0]['condition']['fieldKey'], 'license')

    def test_values_fall_back_to_default(self):
        self.client.force_authenticate(self.player)
        rows = self.client.get(self._values_url()).json()
        self.assertEqual(rows[0]['value'], 100)

    def test_player_cannot_write_value(self):
        self.client.force_authenticate(self.player)
        resp = self.client.patch(
            self._values_url() + '/market_capacity', {'value': 120}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_value_required(self):
        self.client.force_authenticate(self.admin)
        for value in ('', '   ', None):
            with self.subTest(value=value):
                resp = self.client.patch(
                    self._values_url() + '/market_capacity',
                    {'value': value}, format='json')
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertEqual(resp.json()['message'], '字段值必填')

    def test_admin_sets_value_and_reads_back(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            self._values_url() + '/market_capacity', {'value': 120}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['value'], 120)
        rows = self.client.get(self._values_url()).json()
        self.assertEqual(rows[0]['value'], 120)

    def test_unknown_field_value_404(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            self._values_url() + '/no_such_field', {'value': 1}, format='json')
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_condition_validation_sources(self):
        from apps.competition.regions.services import validate_condition

        cleaned, error = validate_condition(
            {'source': 'REGION', 'fieldKey': 'level', 'op': 'eq', 'value': '一线'})
        self.assertEqual(error, '')
        self.assertEqual(cleaned['source'], 'REGION')

        _cleaned, error = validate_condition(
            {'source': 'BAD', 'fieldKey': 'x', 'op': 'eq', 'value': 1})
        self.assertIn('条件来源不支持', error)
