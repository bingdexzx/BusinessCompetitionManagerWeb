"""物资采购合同（记录型）：清单只填数量，单价由基础数据价折算；落账不动库存资金。"""

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import (
    Fuel, Infrastructure, MapNode, MapNodeType, Material, Part, ProductionLine, Product,
    TechNode, Warehouse,
)
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.contracts.models import Contract
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.global_.competitions.models import Competition
from apps.global_.packages.models import Package, PackagePlugin
from apps.global_.plugins.models import PluginRegistry
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db
from plugins_runtime import loader

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)
PLUGIN_REL = 'plugins/wuzicaigouhetong/1.0.0/contract_wuzicaigouhetong.py'
PLUGIN_KEY = 'wuzicaigouhetong'


class SupplyPurchaseContractTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='物资采购赛', code='WZCG', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.user = get_user_model().objects.create_user(
            username='wzcg_user', password='x' * 12, email='wzcg@test.local',
            is_superuser=True)

        # 记录型合同：只观察库存/资金有没有被动过
        for key, name, field_type in (
            ('yuanliaokucun', '原料库存', IndustryField.FieldType.TEXT),
            ('lingjiankucun', '零件库存', IndustryField.FieldType.TEXT),
            ('chanpinkucun', '产品库存', IndustryField.FieldType.TEXT),
            ('yinhangzhanghu', '银行账户', IndustryField.FieldType.NUMBER),
        ):
            IndustryField.objects.create(
                field_key=key, name=name, field_type=field_type,
                data_table=IndustryField.DataTable.ENTITY)

        node_type = MapNodeType.objects.create(name='城市点位')
        MapNode.objects.create(name='松平', region='甲区', node_type=node_type)

        Material.objects.create(
            name='铁', origin='甲区', carbon_emission_coefficient=1.0)
        Part.objects.create(name='齿轮')
        Product.objects.create(name='机床')
        Fuel.objects.create(name='柴油', price_per_liter=6.5)
        TechNode.objects.create(name='自动化产线', research_cost=100)
        Infrastructure.objects.create(name='码头', footprint=10, price=500, activation_price=50)
        Warehouse.objects.create(name='原料仓', capacity=100, price=80, type='MATERIAL')
        ProductionLine.objects.create(
            name='装配线', price=300, labor_count=5, max_per_year=1000)

        self.seller = Company.objects.create(name='卖方公司')
        self.buyer = Company.objects.create(name='买方公司')
        CompanyFieldValue.objects.create(
            company=self.seller, field_key='lingjiankucun', value={'齿轮': 5}, version=1)
        CompanyFieldValue.objects.create(
            company=self.seller, field_key='yinhangzhanghu', value=0, version=1)
        CompanyFieldValue.objects.create(
            company=self.buyer, field_key='lingjiankucun', value={}, version=1)
        CompanyFieldValue.objects.create(
            company=self.buyer, field_key='yinhangzhanghu', value=1000, version=1)

        path = default_storage.path(PLUGIN_REL)
        module, problems = loader.load_plugin(path)
        self.assertEqual(problems, [])
        self.assertEqual(loader.validate_contract_plugin(module), [])
        self.module = module
        registry = PluginRegistry.objects.create(
            kind='CONTRACT', key=PLUGIN_KEY, version='1.0.0',
            sha256=loader.sha256_file(path), name='物资采购合同',
            file_name='contract_wuzicaigouhetong.py', file_path=PLUGIN_REL)
        package = Package.objects.create(
            competition=self.competition, file_name='test.zip',
            status=Package.Status.SUCCESS)
        PackagePlugin.objects.create(
            package=package, plugin=registry, kind='CONTRACT',
            key=PLUGIN_KEY, version='1.0.0')

    def _create(self, inputs, name='物资采购'):
        return engine.create_contract(
            contract_type_key=PLUGIN_KEY,
            plugin_version='1.0.0',
            name=name,
            parties=[
                {'role': '买方', 'companyId': self.buyer.id},
                {'role': '卖方', 'companyId': self.seller.id},
            ],
            inputs=inputs,
            user=self.user,
        )

    def _value(self, company, key):
        ctx.set_competition_context(self.cid, ALIAS)
        row = CompanyFieldValue.objects.filter(company=company, field_key=key).first()
        return row.value if row else None

    def test_schema_only_quantity(self):
        """清单里不再有单价；地点/科技树连数量都没有。"""
        by_key = {item['key']: item for item in self.module.INPUT_SCHEMA}
        for key in ('原料清单', '零件清单', '产品清单', '燃料清单', '基建清单', '仓库清单',
                    '生产线清单'):
            self.assertEqual([f['key'] for f in by_key[key]['fields']], ['quantity'], key)
        self.assertEqual(by_key['地点清单']['fields'], [])
        self.assertEqual(by_key['科技树清单']['fields'], [])

    def test_only_parts_list_posts_and_changes_nothing(self):
        contract = self._create({'零件清单': [{'item': '齿轮', 'quantity': 2}]})
        engine.submit_contract(contract, user=self.user)
        engine.confirm_party(contract, user=self.user)
        engine.confirm_party(contract, user=self.user)
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.POSTED)

        # 记录型：库存与资金都不动
        self.assertEqual(self._value(self.seller, 'lingjiankucun'), {'齿轮': 5})
        self.assertEqual(self._value(self.buyer, 'lingjiankucun'), {})
        self.assertEqual(self._value(self.buyer, 'yinhangzhanghu'), 1000)
        self.assertEqual(self._value(self.seller, 'yinhangzhanghu'), 0)

    def test_all_nine_lists_accepted(self):
        contract = self._create({
            '原料清单': [{'item': '铁', 'quantity': 3}],
            '零件清单': [{'item': '齿轮', 'quantity': 1}],
            '产品清单': [{'item': '机床', 'quantity': 1}],
            '地点清单': [{'item': '松平'}],
            '燃料清单': [{'item': '柴油', 'quantity': 100}],
            '科技树清单': [{'item': '自动化产线'}],
            '基建清单': [{'item': '码头', 'quantity': 1}],
            '仓库清单': [{'item': '原料仓', 'quantity': 2}],
            '生产线清单': [{'item': '装配线', 'quantity': 1}],
        })
        engine.submit_contract(contract, user=self.user)
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.PENDING_PARTY)

    def test_summary_uses_basedata_prices(self):
        contract = self._create({
            '燃料清单': [{'item': '柴油', 'quantity': 2}],
            '仓库清单': [{'item': '原料仓', 'quantity': 2}],
            '基建清单': [{'item': '码头', 'quantity': 1}],
            '生产线清单': [{'item': '装配线', 'quantity': 1}],
            '科技树清单': [{'item': '自动化产线'}],
        })
        context = engine.build_context(contract)
        data = self.module.summary(context)
        # 2×6.5 + 2×80 + 1×500 + 1×300 + 1×100
        self.assertEqual(data['lists']['燃料清单']['amount'], 13.0)
        self.assertEqual(data['lists']['仓库清单']['amount'], 160.0)
        self.assertEqual(data['totalAmount'], 13.0 + 160.0 + 500.0 + 300.0 + 100.0)

    def test_location_and_tech_do_not_need_quantity(self):
        contract = self._create({
            '地点清单': [{'item': '松平'}],
            '科技树清单': [{'item': '自动化产线'}],
        })
        engine.submit_contract(contract, user=self.user)
        contract.refresh_from_db()
        self.assertEqual(contract.status, Contract.Status.PENDING_PARTY)

    def test_all_lists_empty_rejected(self):
        contract = self._create({})
        with self.assertRaises(engine.ContractError) as caught:
            engine.submit_contract(contract, user=self.user)
        self.assertIn('至少要填写一项采购清单', str(caught.exception))

    def test_unknown_part_rejected(self):
        with self.assertRaises(engine.ContractError) as caught:
            self._create({'零件清单': [{'item': '不存在的零件', 'quantity': 1}]})
        self.assertIn('不存在', str(caught.exception))

    def test_unknown_warehouse_rejected(self):
        with self.assertRaises(engine.ContractError) as caught:
            self._create({'仓库清单': [{'item': '不存在的仓库', 'quantity': 1}]})
        self.assertIn('不存在', str(caught.exception))

    def test_quantity_must_be_positive(self):
        with self.assertRaises(engine.ContractError) as caught:
            self._create({'零件清单': [{'item': '齿轮', 'quantity': 0}]})
        message = str(caught.exception)
        self.assertTrue('数量' in message or '小于最小值' in message, message)
