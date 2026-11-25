"""合同删除测试：软删除 / 当前生效轮次回滚 / 状态守卫 / 权限 / 审计 / 补录拒绝。

比赛域模型走多库路由：alias 在导入期注册（系统检查需要），Django 自动建 test 库；
事务回滚不重置序列，URL 用 self.cid 拼接。
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.audit.models import AuditLog
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.fiscal.models import FiscalYear
from apps.competition.industries.models import CompanyFieldValue
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class ContractDeleteTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth import get_user_model

        self.competition = Competition.objects.create(
            name='合同删除测试赛', code='DL', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.manager = get_user_model().objects.create_user(
            username='dmgr', password='x' * 12, email='dmgr@test.local', is_superuser=True)
        CompetitionMembership.objects.create(
            user=self.manager, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN)
        self.player = get_user_model().objects.create_user(
            username='dplayer', password='x' * 12, email='dplayer@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.company = Company.objects.create(name='甲公司')
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def _url(self, pk) -> str:
        return f'/api/competitions/{self.cid}/contracts/{pk}'

    def _list_url(self) -> str:
        return f'/api/competitions/{self.cid}/contracts'

    def _make_contract(self, status=Contract.Status.DRAFT, with_effect=False) -> Contract:
        contract = Contract.objects.create(
            contract_type_key='PO', name='测试合同', status=status,
            parties=[{'role': 'BUYER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='PO-X-FY1-0001', round_no=1 if with_effect else 0,
            created_by=self.manager.id)
        if with_effect:
            ContractFieldEffect.objects.create(
                contract=contract, company=self.company, field_key='cash',
                op=ContractFieldEffect.Op.ADD, value_raw=50,
                before_raw=100, after_raw=150, round_no=1)
            CompanyFieldValue.objects.update_or_create(
                company=self.company, field_key='cash', fiscal_year=None,
                defaults={'value': 150, 'version': 1})
        return contract

    def test_delete_draft_soft_deletes(self):
        """草稿删除：软删除（置 deleted_at），行仍存在，详情 404，列表不出现。"""
        contract = self._make_contract()
        resp = self.client.delete(self._url(contract.id))
        self.assertEqual(resp.status_code, 200, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        contract.refresh_from_db()
        self.assertIsNotNone(contract.deleted_at)
        self.assertTrue(Contract.objects.filter(pk=contract.id).exists())
        # 软删除后详情 GET 404
        resp = self.client.get(self._url(contract.id))
        self.assertEqual(resp.status_code, 404, resp.content)
        # 列表过滤掉软删除合同
        resp = self.client.get(self._list_url())
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['total'], 0)

    def test_delete_blocked_status_400(self):
        """流程中状态（MOD_APPLYING）不可删除：400 且不软删。"""
        contract = self._make_contract(status=Contract.Status.MOD_APPLYING)
        resp = self.client.delete(self._url(contract.id))
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('不允许删除', resp.json()['message'])
        ctx.set_competition_context(self.cid, ALIAS)
        contract.refresh_from_db()
        self.assertIsNone(contract.deleted_at)
        self.assertTrue(Contract.objects.filter(pk=contract.id).exists())

    def test_delete_with_rollback_restores_values_and_keeps_effects(self):
        """删除（回滚）：回滚当前生效轮次恢复字段值；软删但**保留**效果行与审计。"""
        contract = self._make_contract(status=Contract.Status.POSTED, with_effect=True)
        resp = self.client.delete(self._url(contract.id))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['rolledBackRound'], 1)
        ctx.set_competition_context(self.cid, ALIAS)
        contract.refresh_from_db()
        self.assertIsNotNone(contract.deleted_at)
        self.assertTrue(Contract.objects.filter(pk=contract.id).exists())
        # 效果行保留（软删除不再级联删除效果）
        self.assertEqual(ContractFieldEffect.objects.filter(contract=contract).count(), 1)
        # 字段值恢复：ADD 50 被回滚
        row = CompanyFieldValue.objects.get(
            company=self.company, field_key='cash', fiscal_year__isnull=True)
        self.assertEqual(float(row.value), 100.0)
        self.assertTrue(AuditLog.objects.filter(action='CONTRACT_DELETE').exists())

    def test_requires_super_admin(self):
        contract = self._make_contract()
        self.client.force_authenticate(self.player)
        resp = self.client.delete(self._url(contract.id))
        self.assertEqual(resp.status_code, 403, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        contract.refresh_from_db()
        self.assertIsNone(contract.deleted_at)
        self.assertTrue(Contract.objects.filter(pk=contract.id).exists())

    def test_missing_contract_404(self):
        resp = self.client.delete(self._url(999999))
        self.assertEqual(resp.status_code, 404, resp.content)

    def test_backfill_refusal_without_backup(self):
        """补录合同执行：缺财年末备份快照 → 拒绝执行（不落半账）。"""
        fiscal_year = FiscalYear.objects.create(year=1, status=FiscalYear.Status.CLOSED)
        contract = Contract.objects.create(
            contract_type_key='PO', name='补录合同', status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'BUYER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, is_backfill=True, fiscal_year=fiscal_year,
            round_no=0, created_by=self.manager.id)
        with self.assertRaises(engine.ContractError) as cm:
            engine.execute_and_post(contract)
        self.assertIn('缺少财年末备份快照，无法执行补录', str(cm.exception))
        # 未落账：无效果行、状态未变
        self.assertEqual(ContractFieldEffect.objects.filter(contract=contract).count(), 0)
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.PENDING_EXEC)
