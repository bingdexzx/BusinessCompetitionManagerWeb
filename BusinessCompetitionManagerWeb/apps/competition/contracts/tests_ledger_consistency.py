"""账本一致性（2026-11）：当前值以字段真实值为准、排除软删合同、删除补录回滚同步值。"""


from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine, ledger
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.fiscal.models import FiscalYear
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class LedgerConsistencyTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='账本一致性赛', code='LEDG', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='账本公司')
        self.user = User.objects.create_user(
            username='ledger_user', password='x' * 12, email='ledger@test.local')
        IndustryField.objects.create(
            field_key='cash', name='现金', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.ENTITY)
        IndustryField.objects.create(
            field_key='revenue', name='营收', field_type=IndustryField.FieldType.NUMBER,
            data_table=IndustryField.DataTable.FINANCE)
        self._set_base('cash', 150)

    def _set_base(self, key, value):
        CompanyFieldValue.objects.update_or_create(
            company=self.company, field_key=key, fiscal_year=None,
            defaults={'value': value, 'version': 1})

    def _posted_contract(self, number, amount, *, field='cash', is_backfill=False,
                         fiscal_year=None):
        contract = Contract.objects.create(
            contract_type_key='purchase', name='账本合同', status=Contract.Status.POSTED,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number=number, round_no=1,
            numbered_at=timezone.now(), posted_at=timezone.now(),
            is_backfill=is_backfill, fiscal_year=fiscal_year, created_by=self.user.id)
        ContractFieldEffect.objects.create(
            contract=contract, company=self.company, field_key=field,
            op=ContractFieldEffect.Op.ADD, value_raw=amount,
            before_raw=100, after_raw=100 + amount, round_no=1)
        return contract

    def test_current_value_uses_real_field_value(self):
        self._posted_contract('LEDG-FY0-00001', 50)
        # 手工把字段改成 300（不入合同链）
        self._set_base('cash', 300)
        FieldLog.objects.create(
            company=self.company, field_key='cash', data_table='ENTITY',
            event=FieldLog.Event.VALUE_CHANGE, op='SET',
            before_raw=150, after_raw=300, source=FieldLog.Source.MANUAL,
            operator_username='ledger_user')

        chain = ledger.field_chain(self.company.id, 'cash')
        self.assertEqual(float(chain['currentValue']), 300.0)   # 真实值
        self.assertEqual(float(chain['replayValue']), 150.0)    # 只重演合同效果
        self.assertEqual(float(chain['drift']), 150.0)
        self.assertEqual(len(chain['nonContractChanges']), 1)
        self.assertEqual(chain['nonContractChanges'][0]['source'], 'MANUAL')

    def test_deleted_contract_excluded_from_chain(self):
        contract = self._posted_contract('LEDG-FY0-00002', 50)
        contract.deleted_at = timezone.now()
        contract.save(update_fields=['deleted_at'])
        # 删除时已回滚字段值
        self._set_base('cash', 100)

        chain = ledger.field_chain(self.company.id, 'cash')
        self.assertEqual(chain['nodes'], [])
        self.assertEqual(float(chain['currentValue']), 100.0)
        self.assertEqual(float(chain['replayValue']), 100.0)
        self.assertEqual(float(chain['drift']), 0.0)

    def test_delete_backfill_contract_reverts_synced_value(self):
        fiscal_year = FiscalYear.objects.create(year=1, status=FiscalYear.Status.CLOSED)
        contract = self._posted_contract(
            'LEDG-FY1-00003', 50, field='revenue', is_backfill=True,
            fiscal_year=fiscal_year)
        # 补录同步后的当前值（非定时器的 FINANCE 字段才会同步）
        self._set_base('revenue', 150)

        self.assertEqual(
            engine.rollback_backfill_sync(contract, operator=self.user), 1)
        row = CompanyFieldValue.objects.get(
            company=self.company, field_key='revenue', fiscal_year__isnull=True)
        self.assertEqual(float(row.value), 100.0)
        self.assertTrue(FieldLog.objects.filter(
            company=self.company, field_key='revenue',
            source=FieldLog.Source.CONTRACT_ROLLBACK).exists())

    def test_non_backfill_contract_has_nothing_to_revert(self):
        contract = self._posted_contract('LEDG-FY0-00004', 50)
        self.assertEqual(
            engine.rollback_backfill_sync(contract, operator=self.user), 0)
