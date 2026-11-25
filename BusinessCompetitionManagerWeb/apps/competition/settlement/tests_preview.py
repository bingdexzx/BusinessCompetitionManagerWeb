"""结算试算与报告导出（2026-11）：试算不落库、报告导出 xlsx。"""

from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.industries.models import CompanyFieldValue
from apps.competition.settlement.models import ScoringCriterion, SettlementRun
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class SettlementPreviewTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='试算测试赛', code='SP', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.admin = User.objects.create_user(
            username='sp_admin', password='x' * 12, email='sp_admin@test.local',
            is_superuser=True)
        self.player = User.objects.create_user(
            username='sp_player', password='x' * 12, email='sp_player@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)

        for name, revenue in (('甲公司', 100), ('乙公司', 200)):
            company = Company.objects.create(name=name)
            CompanyFieldValue.objects.create(
                company=company, field_key='revenue', fiscal_year=None,
                value=revenue, version=1)
        ScoringCriterion.objects.create(
            name='营收', field_key='revenue', aggregation='SUM',
            direction='HIGHER_BETTER', weight=1.0, enabled=True)

        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_preview_does_not_persist(self):
        response = self.client.post(
            f'/api/competitions/{self.cid}/settlement/preview', {},
            format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body['preview'])
        self.assertEqual(len(body['entries']), 2)
        self.assertEqual(body['entries'][0]['companyName'], '乙公司')
        self.assertEqual(body['entries'][0]['rank'], 1)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(SettlementRun.objects.count(), 0)

    def test_player_cannot_preview(self):
        client = APIClient()
        client.force_authenticate(self.player)
        response = client.post(
            f'/api/competitions/{self.cid}/settlement/preview', {},
            format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 403)

    def test_export_requires_existing_run(self):
        response = self.client.get(
            f'/api/competitions/{self.cid}/settlement/export', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 400)

    def test_export_returns_xlsx_after_run(self):
        run_response = self.client.post(
            f'/api/competitions/{self.cid}/settlement/run', {},
            format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(run_response.status_code, 201, run_response.content)

        response = self.client.get(
            f'/api/competitions/{self.cid}/settlement/export', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response['Content-Type'], XLSX)
        sheet = load_workbook(BytesIO(response.content)).active
        headers = [cell.value for cell in sheet[1]]
        self.assertIn('名次', headers)
        self.assertIn('总分', headers)
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][1], '乙公司')
