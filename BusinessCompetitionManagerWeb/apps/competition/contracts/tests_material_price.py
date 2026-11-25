"""原料参考价查询（2026-11）：原料按地点价格 → 区域参考价 → 合同插件 query_price。"""

import json

from unittest import mock

from django.core.files.storage import default_storage
from django.test import SimpleTestCase, TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import (
    Fuel, Infrastructure, MapNode, MapNodeType, Material, Part, PartMaterial,
    ProductionLine, Product, ProductPart, TechNode, TechPrerequisite, Warehouse,
)
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.global_.competitions.models import Competition
from plugins_runtime import loader
from plugins_runtime.api import ContractContext
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)
PLUGIN_REL = 'plugins/yuancailiaocaigouhetong/1.0.0/contract_yuancailiaocaigouhetong.py'


class _FakeModule:
    PARTY_ROLES = [{'role': '买方'}]
    INPUT_SCHEMA = []

    @staticmethod
    def check(context):
        return []

    @staticmethod
    def apply(context):
        return []


def _plugin_module():
    module, problems = loader.load_plugin(default_storage.path(PLUGIN_REL))
    assert problems == [], problems
    return module


class ContextMaterialPriceTests(SimpleTestCase):
    """ctx.material_price：按区域取价、缺省取全国均价。"""

    def setUp(self):
        self.context = ContractContext(material_prices={
            '铁': {'甲区': 30, '乙区': 40},
            '铜': {'甲区': 100},
        })

    def test_price_by_region(self):
        self.assertEqual(self.context.material_price('铁', '甲区'), 30)
        self.assertEqual(self.context.material_price(' 铁 ', '乙区'), 40)

    def test_missing_region_or_material_returns_default(self):
        self.assertIsNone(self.context.material_price('铁', '丙区'))
        self.assertEqual(self.context.material_price('铁', '丙区', default=0), 0)
        self.assertIsNone(self.context.material_price('不存在', '甲区'))

    def test_price_without_region_is_national_average(self):
        self.assertEqual(self.context.material_price('铁'), 35)
        self.assertEqual(self.context.material_price('铜'), 100)
        self.assertIsNone(self.context.material_price('不存在'))

    def test_price_map_and_names(self):
        self.assertEqual(self.context.material_price_map('铁'), {'甲区': 30, '乙区': 40})
        self.assertEqual(self.context.material_price_map('不存在'), {})
        self.assertEqual(self.context.material_names(), ['铁', '铜'])


class ItemDetailTests(SimpleTestCase):
    """ctx.item_detail：按名称取条目的其它数值。"""

    def setUp(self):
        self.context = ContractContext(item_detail_provider=lambda table: {
            'warehouses': {'原料仓': {'capacity': 100.0, 'price': 80.0, 'type': 'MATERIAL'}},
            'tech_nodes': {'自动化产线': {'research_cost': 100.0, 'description': 'd',
                                          'prerequisites': ['基础机械']}},
        }[table])

    def test_item_detail_by_name(self):
        self.assertEqual(self.context.item_detail('warehouses', '原料仓')['capacity'], 100.0)
        self.assertEqual(self.context.item_detail('tech_nodes', '自动化产线')['prerequisites'],
                         ['基础机械'])

    def test_unknown_item_or_table_returns_default(self):
        self.assertIsNone(self.context.item_detail('warehouses', '不存在'))
        self.assertEqual(self.context.item_detail('warehouses', '不存在', default={}), {})
        self.assertIsNone(self.context.item_detail('parts', '齿轮'))
        self.assertIsNone(self.context.item_detail('warehouses', ''))

    def test_item_names_sorted(self):
        self.assertEqual(self.context.item_names('warehouses'), ['原料仓'])
        self.assertEqual(self.context.item_names('parts'), [])

    def test_details_are_copies(self):
        detail = self.context.item_detail('warehouses', '原料仓')
        detail['capacity'] = 0
        self.assertEqual(self.context.item_detail('warehouses', '原料仓')['capacity'], 100.0)




class EffectApiTests(SimpleTestCase):
    """Effect 规范：简写构造、常量、非法 op。"""

    def test_helpers_equal_full_form(self):
        from plugins_runtime.api import Effect

        self.assertEqual(Effect.add('买方', 'cash', 10),
                         Effect(company='买方', field='cash', op='ADD', value=10))
        self.assertEqual(Effect.sub('买方', 'cash', 10),
                         Effect(company='买方', field='cash', op='SUB', value=10))
        self.assertEqual(Effect.set('买方', 'stock', {'铁': 1}),
                         Effect(company='买方', field='stock', op='SET', value={'铁': 1}))
        self.assertEqual(Effect.add('买方', 'cap', 5, region='甲区').region, '甲区')

    def test_op_constants(self):
        from plugins_runtime.api import Effect

        self.assertEqual((Effect.ADD, Effect.SUB, Effect.SET), ('ADD', 'SUB', 'SET'))

    def test_invalid_op_rejected(self):
        from plugins_runtime.api import Effect

        with self.assertRaises(ValueError):
            Effect(company='买方', field='cash', op='MUL', value=2)

class CanonicalNamesTests(SimpleTestCase):
    """ctx 规范名与弃用别名：两种写法结果一致，查不到返回 None/default。"""

    def setUp(self):
        self.context = ContractContext(
            material_prices={'铁': {'甲区': 30, '乙区': 40}},
            node_regions={'松平': '甲区', '#12': '乙区'},
            node_cities={'松平': '松平', '#12': '江口'},
            item_detail_provider=lambda table: {
                'warehouses': {'原料仓': {'capacity': 100.0, 'price': 80.0, 'type': 'MATERIAL'}},
            }[table],
        )

    def test_item_canonical_equals_alias(self):
        self.assertEqual(self.context.item('warehouses', '原料仓'),
                         self.context.item_detail('warehouses', '原料仓'))
        self.assertEqual(self.context.items('warehouses'),
                         self.context.item_details('warehouses'))
        self.assertIsNone(self.context.item('warehouses', '不存在'))
        self.assertIsNone(self.context.item_detail('warehouses', '不存在'))

    def test_price_canonical_equals_alias(self):
        self.assertEqual(self.context.price('铁', '甲区'), 30)
        self.assertEqual(self.context.price('铁'), 35)
        self.assertEqual(self.context.material_price('铁', '甲区'), 30)
        self.assertEqual(self.context.prices('铁'), {'甲区': 30, '乙区': 40})
        self.assertEqual(self.context.material_price_map('铁'), self.context.prices('铁'))
        self.assertEqual(self.context.price_names(), ['铁'])
        self.assertEqual(self.context.material_names(), ['铁'])
        self.assertIsNone(self.context.price('不存在'))

    def test_node_canonical_accepts_name_and_id(self):
        self.assertEqual(self.context.node_region('松平'), '甲区')
        self.assertEqual(self.context.node_region(12), '乙区')
        self.assertEqual(self.context.node_region('#12'), '乙区')
        self.assertEqual(self.context.node_region('不存在'), '')
        self.assertEqual(self.context.node_region('不存在', '默认区'), '默认区')

        self.assertEqual(self.context.node_city('松平'), '松平')
        self.assertEqual(self.context.node_city(12), '江口')
        self.assertEqual(self.context.node_regions(), {'松平': '甲区'})
        self.assertEqual(self.context.node_cities(), {'松平': '松平'})

    def test_node_aliases_still_work(self):
        self.assertEqual(self.context.region_of('松平'), '甲区')
        self.assertEqual(self.context.region_of_node(12), '乙区')
        self.assertEqual(self.context.city_of('松平'), '松平')
        self.assertEqual(self.context.city_of_node(12), '江口')
        self.assertEqual(self.context.node_region_map(), self.context.node_regions())
        self.assertEqual(self.context.node_city_map(), self.context.node_cities())

class PluginQueryPriceTests(SimpleTestCase):
    """插件对外方法：query_price / query_price_map / fill_unit_price。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plugin = _plugin_module()

    def _context(self):
        return ContractContext(
            material_prices={'铁': {'甲区': 30, '乙区': 40}, '铜': {'甲区': 100}},
            node_regions={'松平': '甲区'},
        )

    def test_query_price_by_material_and_region(self):
        context = self._context()
        self.assertEqual(self.plugin.query_price(context, '铁', '甲区'), 30)
        self.assertEqual(self.plugin.query_price(context, '铜', '甲区'), 100)
        self.assertIsNone(self.plugin.query_price(context, '铁', '丙区'))
        self.assertIsNone(self.plugin.query_price(context, '不存在', '甲区'))

    def test_query_price_without_region_uses_average(self):
        self.assertEqual(self.plugin.query_price(self._context(), '铁'), 35)

    def test_query_price_can_take_region_from_node(self):
        context = self._context()
        region = context.region_of('松平')
        self.assertEqual(region, '甲区')
        self.assertEqual(self.plugin.query_price(context, '铁', region), 30)

    def test_query_price_map(self):
        self.assertEqual(self.plugin.query_price_map(self._context(), '铁'),
                         {'甲区': 30, '乙区': 40})
        self.assertEqual(self.plugin.query_price_map(self._context(), '不存在'), {})

    def test_fill_unit_price_only_fills_blank_rows(self):
        rows = [
            {'item': '铁', 'quantity': 1, 'unitPrice': 0},
            {'item': '铁', 'quantity': 2, 'unitPrice': 99},
            {'item': '不存在', 'quantity': 3, 'unitPrice': 0},
        ]
        filled = self.plugin.fill_unit_price(self._context(), rows, '甲区')
        self.assertEqual(filled, 1)
        self.assertEqual([row['unitPrice'] for row in rows], [30, 99, 0])


class MaterialRegionPriceEngineTests(TestCase):
    """引擎：原料节点价 → 区域参考价，并注入合同 ctx。"""

    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='原料价格赛', code='MPRICE', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        node_type = MapNodeType.objects.create(name='城市点位')
        self.city_a = MapNode.objects.create(
            name='松平', region='甲区', node_type=node_type)
        self.city_b = MapNode.objects.create(
            name='云岭', region='甲区', node_type=node_type)
        self.city_c = MapNode.objects.create(
            name='江口', region='乙区', node_type=node_type)
        self.other = MapNode.objects.create(
            name='矿点1', region='', node_type=node_type)

        Material.objects.create(
            name='铁', origin='甲区', carbon_emission_coefficient=1.0,
            node_prices=json.dumps({
                str(self.city_a.pk): 40,
                str(self.city_b.pk): 20,
                str(self.city_c.pk): 70,
                str(self.other.pk): 999,
            }))
        Material.objects.create(
            name='铜', origin='甲区', carbon_emission_coefficient=1.0,
            node_prices=json.dumps({str(self.city_a.pk): 0}))  # 还没填价

        self.company = Company.objects.create(name='买方公司')

    def test_region_prices_are_averaged_per_region(self):
        prices = engine.material_region_prices()
        self.assertEqual(prices['铁'], {'甲区': 30, '乙区': 70})
        self.assertNotIn('铜', prices)  # 全是空价（0）→ 视作未填

    def test_basedata_item_details_returns_all_fields(self):
        iron = Material.objects.get(name='铁')
        iron.carbon_emission_coefficient = 1.5
        iron.save(update_fields=['carbon_emission_coefficient'])
        gear = Part.objects.create(name='齿轮')
        machine = Product.objects.create(name='机床')
        PartMaterial.objects.create(part=gear, material=iron, ratio=2.0)
        ProductPart.objects.create(product=machine, part=gear, ratio=3.0)
        base = TechNode.objects.create(name='基础机械', research_cost=50)
        advanced = TechNode.objects.create(name='自动化产线', research_cost=100)
        TechPrerequisite.objects.create(node=advanced, prerequisite=base)
        Fuel.objects.create(name='柴油', price_per_liter=6.5)
        Warehouse.objects.create(name='原料仓', capacity=100, price=80, type='MATERIAL')
        ProductionLine.objects.create(
            name='装配线', price=300, labor_count=5, max_per_year=1000)
        Infrastructure.objects.create(name='码头', footprint=10, price=500, activation_price=50)

        materials = engine.basedata_item_details('materials')
        self.assertEqual(materials['铁']['origin'], ['甲区'])
        self.assertEqual(materials['铁']['carbon_emission_coefficient'], 1.5)
        self.assertEqual(materials['铁']['node_prices']['%d' % self.city_a.pk], 40)

        self.assertEqual(engine.basedata_item_details('parts')['齿轮']['materials'],
                         {'铁': 2.0})
        self.assertEqual(engine.basedata_item_details('products')['机床']['parts'],
                         {'齿轮': 3.0})
        tech = engine.basedata_item_details('tech_nodes')['自动化产线']
        self.assertEqual(tech['prerequisites'], ['基础机械'])
        self.assertIn('description', tech)

        self.assertEqual(
            engine.basedata_item_details('fuels')['柴油'], {'price_per_liter': 6.5})
        self.assertEqual(
            set(engine.basedata_item_details('warehouses')['原料仓']),
            {'capacity', 'price', 'type'})
        self.assertEqual(
            engine.basedata_item_details('production_lines')['装配线'],
            {'price': 300.0, 'labor_count': 5.0, 'max_per_year': 1000.0})

        # 全部字段：基建的每一项加成都在
        infrastructure = engine.basedata_item_details('infrastructures')['码头']
        for key in ('footprint', 'price', 'activation_price', 'employment_rate_bonus',
                    'population_bonus', 'high_quality_population_bonus',
                    'happiness_index_bonus', 'per_capita_income_bonus',
                    'carbon_reduction_bonus'):
            self.assertIn(key, infrastructure)
        self.assertEqual(engine.basedata_item_details('map_nodes')['松平']['node_type'],
                         '城市点位')
        self.assertEqual(engine.basedata_item_details('不存在'), {})

    def test_build_context_injects_item_details(self):
        Warehouse.objects.create(name='原料仓', capacity=100, price=80, type='PART')
        with mock.patch.object(engine, 'load_contract_module_simple',
                               return_value=_FakeModule):
            contract = engine.create_contract(
                contract_type_key='city_deal', plugin_version='1.0.0', name='采购',
                parties=[{'role': '买方', 'companyId': self.company.id}],
                inputs={}, user=mock.Mock(id=1))
        context = engine.build_context(contract)
        self.assertEqual(context.item_detail('warehouses', '原料仓')['type'], 'PART')

    def test_build_context_injects_material_prices(self):
        with mock.patch.object(engine, 'load_contract_module_simple',
                               return_value=_FakeModule):
            contract = engine.create_contract(
                contract_type_key='city_deal', plugin_version='1.0.0', name='原料采购',
                parties=[{'role': '买方', 'companyId': self.company.id}],
                inputs={}, user=mock.Mock(id=1))
        context = engine.build_context(contract)
        self.assertEqual(context.material_price('铁', '甲区'), 30)
        self.assertEqual(context.material_price('铁', '乙区'), 70)
        self.assertEqual(context.material_price('铁'), 50)
        self.assertIsNone(context.material_price('铜', '甲区'))
