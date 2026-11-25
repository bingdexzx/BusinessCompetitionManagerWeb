"""LIST 类型输入（原料清单，2026-11）：校验、存储、插件读取、试跑样例。"""

from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import Material
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.dryrun import dry_run_contract_plugin
from apps.global_.competitions.models import Competition
from plugins_runtime.api import ContractContext
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class _FakeModule:
    PARTY_ROLES = [{'role': 'buyer'}]
    INPUT_SCHEMA = [
        {
            'key': 'materials',
            'label': '原料清单',
            'type': 'LIST:materials',
            'itemLabel': '原料',
            'minItems': 1,
            'fields': [{'key': 'quantity', 'label': '数量', 'type': 'NUMBER', 'min': 1}],
        },
    ]

    @staticmethod
    def check(context):
        return []

    @staticmethod
    def apply(context):
        return []


class MaterialListValidationTests(SimpleTestCase):
    def setUp(self):
        self.module = _FakeModule
        self.parties = [{'role': 'buyer', 'companyId': 1}]

    def test_missing_list_rejected(self):
        problems = engine._validate_inputs(self.module, self.parties, {})
        self.assertTrue(any('缺少输入项 原料清单' in p for p in problems), problems)

    def test_empty_list_rejected(self):
        problems = engine._validate_inputs(self.module, self.parties, {'materials': []})
        self.assertTrue(any('缺少输入项 原料清单' in p for p in problems), problems)

    def test_row_without_item_rejected(self):
        problems = engine._validate_inputs(
            self.module, self.parties, {'materials': [{'quantity': 3}]})
        self.assertTrue(any('缺少原料' in p for p in problems), problems)

    def test_row_quantity_must_be_number(self):
        problems = engine._validate_inputs(
            self.module, self.parties, {'materials': [{'item': '铁', 'quantity': 'abc'}]})
        self.assertTrue(any('数量不是数字' in p for p in problems), problems)

    def test_row_quantity_min(self):
        problems = engine._validate_inputs(
            self.module, self.parties, {'materials': [{'item': '铁', 'quantity': 0}]})
        self.assertTrue(any('小于最小值' in p for p in problems), problems)



class NewInputTypesTests(TestCase):
    """2026-11 新增：REF 下拉校验、载具/城市/公司清单、配套 item_detail。"""

    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        from apps.competition.basedata.models import Fuel, MapNode, MapNodeType, Vehicle

        self.competition = Competition.objects.create(
            name='输入项赛', code='INTYPES', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.buyer = Company.objects.create(name='买方公司', industry_key='industry1')
        self.seller = Company.objects.create(name='卖方公司')

        fuel = Fuel.objects.create(name='柴油', price_per_liter=6.5)
        Vehicle.objects.create(
            name='卡车', fuel=fuel, fuel_consumption_per_km=0.2,
            max_material_cargo=10, max_part_cargo=5, max_product_cargo=2,
            price=120, carbon_emission=1.5)
        city_type = MapNodeType.objects.create(name='城市点位')
        mine_type = MapNodeType.objects.create(name='矿点')
        MapNode.objects.create(name='松平', region='甲区', node_type=city_type)
        MapNode.objects.create(name='铁矿1', region='甲区', node_type=mine_type)

        self.module = _FakeModule  # 只有空 schema，下面按需替换
        self.parties = [{'role': 'buyer', 'companyId': self.buyer.id}]

    def _validate(self, schema, inputs):
        module = type('M', (), {
            'PARTY_ROLES': [{'role': 'buyer', 'label': '买方'}],
            'INPUT_SCHEMA': schema,
            'check': staticmethod(lambda c: []),
            'apply': staticmethod(lambda c: []),
        })
        return engine._validate_inputs(module, self.parties, inputs)

    def test_ref_company_must_exist(self):
        schema = [{'key': 'company', 'label': '公司', 'type': 'REF:companies'}]
        self.assertEqual(self._validate(schema, {'company': '卖方公司'}), [])
        problems = self._validate(schema, {'company': '不存在公司'})
        self.assertTrue(any('不存在' in p for p in problems), problems)

    def test_ref_city_only_accepts_city_nodes(self):
        schema = [{'key': 'city', 'label': '地点', 'type': 'REF:cities'}]
        self.assertEqual(self._validate(schema, {'city': '松平'}), [])
        problems = self._validate(schema, {'city': '铁矿1'})
        self.assertTrue(any('不存在' in p for p in problems), problems)

    def test_ref_region_accepts_map_region(self):
        schema = [{'key': 'region', 'label': '区域', 'type': 'REF:regions'}]
        self.assertEqual(self._validate(schema, {'region': '甲区'}), [])
        self.assertTrue(self._validate(schema, {'region': '不存在区'}))

    def test_vehicle_list_requires_existing_vehicle(self):
        schema = [{
            'key': 'vehicles', 'label': '载具清单', 'type': 'LIST:vehicles',
            'itemLabel': '载具',
            'fields': [{'key': 'quantity', 'label': '数量', 'type': 'NUMBER', 'min': 1}],
        }]
        self.assertEqual(
            self._validate(schema, {'vehicles': [{'item': '卡车', 'quantity': 2}]}), [])
        problems = self._validate(schema, {'vehicles': [{'item': '飞机', 'quantity': 1}]})
        self.assertTrue(any('不存在' in p for p in problems), problems)

    def test_company_and_city_lists(self):
        schema = [
            {'key': 'companies', 'label': '公司清单', 'type': 'LIST:companies',
             'itemLabel': '公司', 'fields': []},
            {'key': 'cities', 'label': '城市清单', 'type': 'LIST:cities',
             'itemLabel': '城市', 'fields': []},
        ]
        self.assertEqual(
            self._validate(schema, {
                'companies': [{'item': '卖方公司'}],
                'cities': [{'item': '松平'}],
            }),
            [],
        )
        problems = self._validate(schema, {
            'companies': [{'item': '不存在公司'}],
            'cities': [{'item': '铁矿1'}],
        })
        self.assertEqual(len(problems), 2, problems)

    def test_item_details_for_new_tables(self):
        ctx.set_competition_context(self.cid, ALIAS)
        vehicles = engine.basedata_item_details('vehicles')
        self.assertEqual(vehicles['卡车']['price'], 120.0)
        self.assertEqual(vehicles['卡车']['fuel'], '柴油')

        cities = engine.basedata_item_details('cities')
        self.assertIn('松平', cities)
        self.assertNotIn('铁矿1', cities)
        self.assertEqual(cities['松平']['region'], '甲区')

        companies = engine.basedata_item_details('companies')
        self.assertEqual(companies['买方公司']['industry'], 'industry1')

class MaterialListStorageTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='原料清单赛', code='MLIST', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='买方公司')
        Material.objects.create(name='铁', origin='甲', carbon_emission_coefficient=1.0)

    def test_valid_list_passes_and_unknown_material_rejected(self):
        with mock.patch.object(engine, 'load_contract_module_simple', return_value=_FakeModule):
            contract = engine.create_contract(
                contract_type_key='city_deal', plugin_version='1.0.0', name='原料合同',
                parties=[{'role': 'buyer', 'companyId': self.company.id}],
                inputs={'materials': [{'item': '铁', 'quantity': 10}]},
                user=mock.Mock(id=1))
            self.assertEqual(contract.inputs['materials'][0]['item'], '铁')

            with self.assertRaises(engine.ContractError) as caught:
                engine.create_contract(
                    contract_type_key='city_deal', plugin_version='1.0.0', name='坏原料',
                    parties=[{'role': 'buyer', 'companyId': self.company.id}],
                    inputs={'materials': [{'item': '不存在', 'quantity': 1}]},
                    user=mock.Mock(id=1))
        self.assertIn('不存在', str(caught.exception))

    def test_plugin_reads_list_via_ctx(self):
        context = ContractContext(inputs={
            'materials': [{'item': '铁', 'quantity': '10'}, {'item': '铜', 'quantity': 2}],
        })
        rows = context.input_list('materials')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['item'], '铁')
        self.assertEqual(context.number(rows[0]['quantity']), 10.0)
        self.assertEqual(context.input_list('不存在'), [])

    def test_dry_run_synthesizes_one_row(self):
        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_FakeModule):
            result = dry_run_contract_plugin(contract_type_key='city_deal')
        rows = result['inputs']['materials']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['item'], '铁')
        self.assertEqual(rows[0]['quantity'], 1)
