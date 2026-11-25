"""冻结口径测试（2026-11）：仅在合同修改期间冻结参与方公司全部资源。

- 落账本身不冻结，手工修改正常；
- 申请修改 → 整公司资源冻结（哨兵 field_key='*'），只允许该合同自己的修改流程改字段；
- 审核驳回 / 其他方驳回 / 修改完成 → 自动解冻。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.competition.ledger.models import ContractFreeze
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)
User = get_user_model()


class FreezeScopeTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='冻结口径赛', code='FRZ', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.user = User.objects.create_user(
            username='frz_admin', password='x' * 12, email='frz_admin@test.local',
            is_superuser=True)
        self.company = Company.objects.create(name='冻结公司')
        self.contract = Contract.objects.create(
            contract_type_key='PO', name='冻结合同', status=Contract.Status.POSTED,
            parties=[{'role': 'BUYER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'quantity': 1}, unified_number='PO-A-FY1-0001', round_no=1,
            created_by=self.user.id,
        )

    def tearDown(self):
        ctx.clear_request_context()

    def test_posted_contract_does_not_freeze_manual_edit(self):
        """落账合同不再长期冻结字段：手工修改不受影响。"""
        engine.assert_field_writable(self.company.id, 'cash')  # 不应抛异常

    def test_modification_freezes_all_resources_and_reject_unfreezes(self):
        engine.request_modify(self.contract, user=self.user, reason='测试修改')
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.MOD_APPLYING)
        self.assertTrue(ContractFreeze.objects.filter(
            contract=self.contract, field_key=engine.ALL_FIELDS, unfrozen_at__isnull=True).exists())

        # 冻结期间：整公司任意字段都不允许手工改
        with self.assertRaises(engine.ContractError):
            engine.assert_field_writable(self.company.id, 'cash')

        # 驳回 → 回到落账态并解冻
        engine.review_modify(self.contract, user=self.user, approve=False)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.POSTED)
        self.assertFalse(ContractFreeze.objects.filter(
            contract=self.contract, unfrozen_at__isnull=True).exists())
        engine.assert_field_writable(self.company.id, 'cash')

    def test_approve_keeps_frozen_until_completion(self):
        engine.request_modify(self.contract, user=self.user, reason='测试修改')
        engine.review_modify(self.contract, user=self.user, approve=True)
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.status, Contract.Status.MOD_EDITING)
        with self.assertRaises(engine.ContractError):
            engine.assert_field_writable(self.company.id, 'cash')

    def test_other_contract_cannot_execute_during_modification(self):
        engine.request_modify(self.contract, user=self.user, reason='测试修改')
        other = Contract.objects.create(
            contract_type_key='PO', name='另一份合同', status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'SELLER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'quantity': 2}, created_by=self.user.id,
        )
        with self.assertRaises(engine.ContractError):
            engine._assert_no_active_modification(other)

    def test_second_modification_request_blocked_while_frozen(self):
        """同一公司同时只允许一个合同修改：第二份合同申请修改被拒。"""
        engine.request_modify(self.contract, user=self.user, reason='第一份修改')
        other = Contract.objects.create(
            contract_type_key='PO', name='第二份合同', status=Contract.Status.POSTED,
            parties=[{'role': 'SELLER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'quantity': 3}, unified_number='PO-A-FY1-0002', round_no=1,
            created_by=self.user.id,
        )
        with self.assertRaises(engine.ContractError):
            engine.request_modify(other, user=self.user, reason='第二份修改')
