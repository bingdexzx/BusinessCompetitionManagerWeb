"""公司字段修改 API：手工修改视为「填值」——空值 / 空白一律 400，0 与 false 是合法值。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.industries.models import IndustryField
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class CompanyFieldUpdateTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='字段必填赛', code='REQ', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.user = get_user_model().objects.create_user(
            username='req_admin', password='x' * 12, email='req_admin@test.local',
            is_superuser=True)
        self.company = Company.objects.create(name='必填公司')
        # 手工改字段现在要求字段已定义（2026-11）
        IndustryField.objects.create(
            field_key='capacity', name='产能', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _url(self) -> str:
        return f'/api/competitions/{self.cid}/companies/{self.company.id}/fields'

    def test_empty_value_rejected(self):
        for value in (None, '', '   '):
            with self.subTest(value=value):
                resp = self.client.patch(
                    self._url(), {'fieldKey': 'capacity', 'value': value}, format='json')
                self.assertEqual(resp.status_code, 400, resp.content)
                self.assertEqual(resp.json()['message'], '字段值必填')

    def test_valid_value_saved(self):
        resp = self.client.patch(
            self._url(), {'fieldKey': 'capacity', 'value': 5}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['value'], 5)

    def test_zero_and_false_are_valid_values(self):
        for value in (0, False):
            with self.subTest(value=value):
                resp = self.client.patch(
                    self._url(), {'fieldKey': 'capacity', 'value': value}, format='json')
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertEqual(resp.json()['value'], value)
