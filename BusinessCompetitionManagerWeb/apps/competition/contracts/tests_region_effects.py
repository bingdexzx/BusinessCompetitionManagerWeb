"""区域字段合同落账（2026-11）：按条件校验 → 写区域值 → 审计/日志 → 回滚。"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract, ContractFieldEffect
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.industries.models import CompanyFieldValue
from apps.competition.regions import services as region_services
from apps.competition.regions.models import Region, RegionField, RegionFieldValue
from apps.global_.competitions.models import Competition
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db
from plugins_runtime.api import Effect

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)
User = get_user_model()


class RegionFieldEffectTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='区域效果赛', code='RFE', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.user = User.objects.create_user(
            username='rfe_admin', password='x' * 12, email='rfe_admin@test.local',
            is_superuser=True)
        self.company = Company.objects.create(name='区域公司')
        CompanyFieldValue.objects.create(
            company=self.company, field_key='license', value=True, version=1)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='location', value='"华东"', version=1)

        self.region = Region.objects.create(name='华东')
        self.field = RegionField.objects.create(
            field_key='market_capacity', name='市场容量',
            field_type=RegionField.FieldType.NUMBER, default_value=100,
            condition={'fieldKey': 'license', 'op': 'eq', 'value': True},
        )
        RegionFieldValue.objects.create(
            region=self.region, field_key='market_capacity', value=100, version=1)
        self.contract = Contract.objects.create(
            contract_type_key='PO', name='区域合同', status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'BUYER', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={'quantity': 1}, round_no=1, created_by=self.user.id,
        )

    def tearDown(self):
        ctx.clear_request_context()

    def _apply(self, effects):
        return engine.apply_effects(
            self.contract, effects, source=FieldLog.Source.CONTRACT_POST,
            operator=self.user)

    def test_condition_passed_writes_region_value(self):
        self._apply([Effect('BUYER', 'market_capacity', 'ADD', 50, region='华东')])

        self.assertEqual(
            region_services.read_region_value(self.region.id, 'market_capacity'), 150)
        effect = ContractFieldEffect.objects.get(contract=self.contract)
        self.assertEqual(effect.region_id, self.region.id)
        self.assertEqual(effect.company_id, self.company.id)
        self.assertEqual(effect.after_raw, 150)

        log = FieldLog.objects.get(contract=self.contract, field_key='market_capacity')
        self.assertEqual(log.region_id, self.region.id)
        self.assertEqual(log.data_table, 'REGION')
        self.assertEqual(log.after_raw, 150)

    def test_company_must_belong_to_region(self):
        """公司「所在区域」≠ 目标区域时，不能修改该区域字段。"""
        CompanyFieldValue.objects.filter(
            company=self.company, field_key='location').update(value='"华南"')
        with self.assertRaises(engine.ContractError):
            self._apply([Effect('BUYER', 'market_capacity', 'ADD', 50, region='华东')])
        self.assertEqual(
            region_services.read_region_value(self.region.id, 'market_capacity'), 100)

    def test_multi_region_location_allowed(self):
        """所在区域支持多值：包含目标区域名即可。"""
        CompanyFieldValue.objects.filter(
            company=self.company, field_key='location').update(value='"华南,华东"')
        self._apply([Effect('BUYER', 'market_capacity', 'ADD', 10, region='华东')])
        self.assertEqual(
            region_services.read_region_value(self.region.id, 'market_capacity'), 110)

    def test_region_field_condition(self):
        """附加条件可引用目标区域的其他区域字段。"""
        RegionField.objects.create(
            field_key='level', name='区域等级',
            field_type=RegionField.FieldType.TEXT, default_value='一线')
        RegionFieldValue.objects.create(
            region=self.region, field_key='level', value='一线', version=1)
        self.field.condition = {
            'source': 'REGION', 'fieldKey': 'level', 'op': 'eq', 'value': '一线'}
        self.field.save(update_fields=['condition'])

        self._apply([Effect('BUYER', 'market_capacity', 'ADD', 5, region='华东')])
        self.assertEqual(
            region_services.read_region_value(self.region.id, 'market_capacity'), 105)

        RegionFieldValue.objects.filter(
            region=self.region, field_key='level').update(value='二线')
        with self.assertRaises(engine.ContractError):
            self._apply([Effect('BUYER', 'market_capacity', 'ADD', 5, region='华东')])

    def test_condition_failed_blocks_effect(self):
        CompanyFieldValue.objects.filter(
            company=self.company, field_key='license').update(value=False)
        with self.assertRaises(engine.ContractError):
            self._apply([Effect('BUYER', 'market_capacity', 'ADD', 50, region='华东')])
        self.assertEqual(
            region_services.read_region_value(self.region.id, 'market_capacity'), 100)

    def test_unknown_region_field_blocked(self):
        with self.assertRaises(engine.ContractError):
            self._apply([Effect('BUYER', 'no_such_field', 'ADD', 1, region='华东')])

    def test_rollback_restores_region_value(self):
        self._apply([Effect('BUYER', 'market_capacity', 'ADD', 50, region='华东')])
        engine.rollback_round(self.contract, operator=self.user)
        self.assertEqual(
            region_services.read_region_value(self.region.id, 'market_capacity'), 100)
