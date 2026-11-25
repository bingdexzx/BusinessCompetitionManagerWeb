"""手工改字段（2026-11）：禁改公式字段、按类型与 min/max 校验、version 做真正的 CAS。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class FieldUpdateGuardTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='字段校验赛', code='FGUARD', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='字段公司')
        self.user = User.objects.create_user(
            username='fguard', password='x' * 12, email='fguard@test.local')
        CompetitionMembership.objects.create(
            user=self.user, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN,
            managed_companies=[self.company.id])
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        IndustryField.objects.create(
            field_key='cash', name='现金', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY, meta={'min': 0, 'max': 1000})
        IndustryField.objects.create(
            field_key='capacity', name='产能', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        IndustryField.objects.create(
            field_key='loan_limit', name='贷款额度', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.FINANCE,
            formula='cash * 0.5', is_calculated=True)

    def _patch(self, **payload):
        return self.client.patch(
            f'/api/competitions/{self.cid}/companies/{self.company.id}/fields',
            payload, format='json', HTTP_HOST='127.0.0.1')

    def test_calculated_field_cannot_be_edited(self):
        response = self._patch(fieldKey='loan_limit', value=100)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('公式', response.json()['message'])

    def test_unknown_field_rejected(self):
        response = self._patch(fieldKey='nope', value=1)
        self.assertEqual(response.status_code, 400)

    def test_number_type_and_range_validated(self):
        self.assertEqual(self._patch(fieldKey='cash', value='abc').status_code, 400)
        self.assertEqual(self._patch(fieldKey='cash', value=-5).status_code, 400)
        self.assertEqual(self._patch(fieldKey='cash', value=5000).status_code, 400)
        self.assertEqual(self._patch(fieldKey='cash', value=500).status_code, 200)

    def test_version_cas_conflict(self):
        ctx.set_competition_context(self.cid, ALIAS)
        first = self._patch(fieldKey='cash', value=100)
        self.assertEqual(first.status_code, 200, first.content)
        version = first.json()['version']

        stale = self._patch(fieldKey='cash', value=200, expectedVersion=version - 1)
        self.assertEqual(stale.status_code, 409, stale.content)

        fresh = self._patch(fieldKey='cash', value=200, expectedVersion=version)
        self.assertEqual(fresh.status_code, 200, fresh.content)
        ctx.set_competition_context(self.cid, ALIAS)
        row = CompanyFieldValue.objects.get(
            company=self.company, field_key='cash', fiscal_year__isnull=True)
        self.assertEqual(float(row.value), 200.0)
        self.assertEqual(row.version, version + 1)

    def test_table_exposes_versions_for_cas(self):
        self._patch(fieldKey='capacity', value=7)
        response = self.client.get(
            f'/api/competitions/{self.cid}/companies/{self.company.id}/tables/entity',
            HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        fields = {f['key']: f for f in response.json()['fields']}
        self.assertIn('versions', fields['capacity'])
        versions = fields['capacity']['versions']
        # 实体字段无财年：JSON 键会变成字符串 "null"
        self.assertEqual(len(versions), 1, versions)
        self.assertEqual(list(versions.values())[0], 1)
        self.assertIsNone(fields['capacity']['min'])
