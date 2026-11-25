"""补录场景测试：FY0 产能 300，FY1 计时器清零后补录 FY0。

覆盖：
- 补录提交/执行检查使用所补录财年备份快照（不是当前值）；
- 计时器实体字段补录不回写当前值（避免污染 FY1）；
- 非计时器实体字段（产品库存）补录后同步到当前数据。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.competition.fiscal.models import FiscalYear, FiscalYearBackup
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.companies.models import Company
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db
from plugins_runtime.api import Effect

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class _BackfillModule:
    PARTY_ROLES = [{'role': 'buyer', 'label': '买方'}]
    INPUT_SCHEMA = [{'key': 'quantity', 'label': '数量', 'type': 'NUMBER'}]

    @staticmethod
    def check(contract_ctx):
        capacity = contract_ctx.company_field('buyer', 'capacity', 0)
        quantity = contract_ctx.input('quantity') or 0
        problems = []
        if capacity < quantity:
            problems.append('产能不足')
        return problems

    @staticmethod
    def apply(contract_ctx):
        quantity = contract_ctx.input('quantity') or 0
        return [
            Effect('buyer', 'capacity', 'SUB', quantity),
            Effect('buyer', 'product', 'ADD', quantity),
        ]


class BackfillCapacityScenarioTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='补录产能赛', code='BF', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.user = get_user_model().objects.create_user(
            username='bf_admin', password='x' * 12, email='bf_admin@test.local',
            is_superuser=True)
        self.company = Company.objects.create(name='A公司')
        IndustryField.objects.create(
            field_key='capacity', name='产能', field_type='NUMBER',
            data_table=IndustryField.DataTable.ENTITY, timer_enabled=True,
            timer_trigger=IndustryField.TimerTrigger.FY_START)
        IndustryField.objects.create(
            field_key='product', name='产品库存', field_type='NUMBER',
            data_table=IndustryField.DataTable.ENTITY)
        # FY0 关闭时快照：产能 300
        self.fy0 = FiscalYear.objects.create(year=0, status=FiscalYear.Status.CLOSED)
        FiscalYearBackup.objects.create(
            fiscal_year=self.fy0, company=self.company, snapshot={'capacity': 300})
        # FY1 开始：计时器把当前产能清零
        self.fy1 = FiscalYear.objects.create(year=1, status=FiscalYear.Status.OPEN)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='capacity', value=0, version=1)

        # 替换插件加载，避免依赖比赛包
        self._orig_load = engine.load_contract_module
        engine.load_contract_module = lambda contract: _BackfillModule

    def tearDown(self):
        engine.load_contract_module = self._orig_load
        ctx.clear_request_context()

    def _create_backfill(self, quantity: int) -> Contract:
        return Contract.objects.create(
            name='补录生产', contract_type_key='produce',
            status=Contract.Status.BACKFILL_REVIEW,
            parties=[{'role': 'buyer', 'companyId': self.company.id}],
            inputs={'quantity': quantity}, fiscal_year=self.fy0,
            created_by=self.user.id, is_backfill=True,
        )

    def test_backfill_uses_fiscal_backup_and_keeps_timer_value(self):
        contract = self._create_backfill(100)
        engine.review_backfill(contract, user=self.user, approve=True)
        engine.submit_contract(contract, user=self.user)
        self.assertEqual(contract.status, Contract.Status.PENDING_PARTY)

        engine.confirm_party(contract, user=self.user)
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.POSTED)

        # 计时器实体字段：补录只做历史审计，不把 FY0 结果写回 FY1 当前值
        capacity = CompanyFieldValue.objects.get(
            company=self.company, field_key='capacity', fiscal_year__isnull=True)
        self.assertEqual(capacity.value, 0)

        # 非计时器实体字段：产品库存同步到当前
        product = CompanyFieldValue.objects.get(
            company=self.company, field_key='product', fiscal_year__isnull=True)
        self.assertEqual(product.value, 100)

        # 效果审计记录补录后的历史值
        effect = contract.effects.get(field_key='capacity')
        self.assertEqual(effect.before_raw, 300)
        self.assertEqual(effect.after_raw, 200)

    def test_second_backfill_sees_prior_backfill(self):
        """同财年多张补录：第二张的历史基准 = 快照 + 已落账补录效果。"""
        first = self._create_backfill(100)
        engine.review_backfill(first, user=self.user, approve=True)
        engine.submit_contract(first, user=self.user)
        engine.confirm_party(first, user=self.user)
        first.refresh_from_db()
        self.assertEqual(first.status, Contract.Status.POSTED)

        second = self._create_backfill(150)
        engine.review_backfill(second, user=self.user, approve=True)
        engine.submit_contract(second, user=self.user)  # 若未重放第一张，基准仍 300 → 误判可用 300
        engine.confirm_party(second, user=self.user)
        second.refresh_from_db()
        self.assertEqual(second.status, Contract.Status.POSTED)
        self.assertEqual(second.effects.get(field_key='capacity').before_raw, 200)
        self.assertEqual(second.effects.get(field_key='capacity').after_raw, 50)

        third = self._create_backfill(100)
        engine.review_backfill(third, user=self.user, approve=True)
        with self.assertRaises(engine.CheckFailedError):
            engine.submit_contract(third, user=self.user)  # 剩余产能 50，不够 100
