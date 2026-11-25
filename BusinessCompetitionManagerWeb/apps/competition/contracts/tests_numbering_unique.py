"""统一编号（2026-11）：比赛内唯一；流水键用比赛 ID，改比赛代码不重号。"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class ContractNumberingTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='编号测试赛', code='AAA', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='编号公司')
        self.user = User.objects.create_user(
            username='num_user', password='x' * 12, email='num@test.local')

    def _contract(self, number=''):
        return Contract.objects.create(
            contract_type_key='purchase', name='编号合同',
            status=Contract.Status.DRAFT,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number=number, round_no=0, created_by=self.user.id)

    def test_number_is_unique_within_competition(self):
        self._contract('AAA-FY0-00001')
        with self.assertRaises(IntegrityError):
            with transaction.atomic(using=ALIAS):
                self._contract('AAA-FY0-00001')

    def test_empty_number_allowed_for_many_drafts(self):
        self._contract('')
        self._contract('')
        self.assertEqual(Contract.objects.filter(unified_number='').count(), 2)

    def test_sequence_key_uses_competition_id_not_code(self):
        contract = self._contract()
        first = engine.generate_unified_number(contract, self.competition)
        self.assertEqual(first, 'AAA-FY0-00001')

        # 管理员改比赛代码：编号前缀跟着变，但流水接着往上走（不回到 1）
        self.competition.code = 'BBB'
        self.competition.save(update_fields=['code'])
        second = engine.generate_unified_number(contract,
                                                Competition.objects.get(pk=self.cid))
        self.assertEqual(second, 'BBB-FY0-00002')

        # 编号重复：唯一约束挡住
        self._contract('BBB-FY0-00002')
        with self.assertRaises(IntegrityError):
            with transaction.atomic(using=ALIAS):
                self._contract('BBB-FY0-00002')
