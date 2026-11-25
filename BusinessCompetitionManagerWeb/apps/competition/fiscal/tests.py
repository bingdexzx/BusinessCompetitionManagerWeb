"""财年编排：从第 0 财年开始（2026-11 口径）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.fiscal import services as fiscal_services
from apps.competition.fiscal.models import FiscalYear
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class FiscalYearSequenceTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='财年序列赛', code='FY', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.user = get_user_model().objects.create_user(
            username='fy_admin', password='x' * 12, email='fy_admin@test.local',
            is_superuser=True)

    def tearDown(self):
        ctx.clear_request_context()

    def test_first_year_is_zero_then_increments(self):
        first = fiscal_services.open_fiscal_year(user=self.user)
        self.assertEqual(first.year, 0)
        fiscal_services.close_fiscal_year(user=self.user)

        second = fiscal_services.open_fiscal_year(user=self.user)
        self.assertEqual(second.year, 1)
        self.assertEqual(
            list(FiscalYear.objects.order_by('year').values_list('year', flat=True)),
            [0, 1],
        )
