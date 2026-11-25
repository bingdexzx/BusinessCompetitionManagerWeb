"""合同统一编号：比赛代码-FY财年-5位自增流水。"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract, NumberSequence
from apps.competition.fiscal.models import FiscalYear
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class UnifiedNumberTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='编号赛', code='C9', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.user = get_user_model().objects.create_user(
            username='num_admin', password='x' * 12, email='num_admin@test.local',
            is_superuser=True)
        self.fy = FiscalYear.objects.create(year=0)
        self.contract = Contract.objects.create(
            contract_type_key='PO', status=Contract.Status.PENDING_EXEC,
            parties=[], inputs={}, fiscal_year=self.fy, created_by=self.user.id)

    def tearDown(self):
        ctx.clear_request_context()

    def test_format_and_increment(self):
        first = engine.generate_unified_number(self.contract, self.competition)
        second = engine.generate_unified_number(self.contract, self.competition)
        self.assertEqual(first, 'C9-FY0-00001')
        self.assertEqual(second, 'C9-FY0-00002')
        # 同一比赛+财年共用一个序列（键用比赛 ID，不按合同类别分段；改比赛代码不重号）
        self.assertTrue(
            NumberSequence.objects.filter(key=f'cid{self.competition.id}-FY0').exists())

    def test_other_fiscal_year_has_own_sequence(self):
        fy1 = FiscalYear.objects.create(year=1)
        self.contract.fiscal_year = fy1
        number = engine.generate_unified_number(self.contract, self.competition)
        self.assertEqual(number, 'C9-FY1-00001')
