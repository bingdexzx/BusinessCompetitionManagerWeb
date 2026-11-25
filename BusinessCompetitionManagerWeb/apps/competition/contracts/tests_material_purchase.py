"""原料采购合同（新增合同类型）：清单输入 → 库存/资金划转 → 校验。

用真实插件文件（media/plugins/yuancailiaocaigouhetong/1.0.0）跑通创建到落账。
"""

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.test import TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import Material
from apps.competition.companies.models import Company
from apps.competition.contracts import engine
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.global_.competitions.models import Competition
from apps.global_.packages.models import Package, PackagePlugin
from apps.global_.plugins.models import PluginRegistry
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db
from plugins_runtime import loader

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)
PLUGIN_REL = 'plugins/yuancailiaocaigouhetong/1.0.0/contract_yuancailiaocaigouhetong.py'
PLUGIN_KEY = 'yuancailiaocaigouhetong'


class MaterialPurchaseContractTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='原料采购赛', code='MPC', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.user = get_user_model().objects.create_user(
            username='mpc_user', password='x' * 12, email='mpc@test.local',
            is_superuser=True)

        for key, name, field_type in (
            ('yuanliaokucun', '原料库存', IndustryField.FieldType.TEXT),
            ('yinhangzhanghu', '银行账户', IndustryField.FieldType.NUMBER),
        ):
            IndustryField.objects.create(
                field_key=key, name=name, field_type=field_type,
                data_table=IndustryField.DataTable.ENTITY)

        for material_name in ('铁', '铜'):
            Material.objects.create(
                name=material_name, origin='甲', carbon_emission_coefficient=1.0)

        self.seller = Company.objects.create(name='卖方公司')
        self.buyer = Company.objects.create(name='买方公司')
        CompanyFieldValue.objects.create(
            company=self.seller, field_key='yuanliaokucun',
            value={'铁': 100, '铜': 5}, version=1)
        CompanyFieldValue.objects.create(
            company=self.seller, field_key='yinhangzhanghu', value=0, version=1)
        CompanyFieldValue.objects.create(
            company=self.buyer, field_key='yuanliaokucun', value={}, version=1)
        CompanyFieldValue.objects.create(
            company=self.buyer, field_key='yinhangzhanghu', value=1000, version=1)

        # 注册真实插件文件（与比赛包导入同样登记 registry + 关联）
        path = default_storage.path(PLUGIN_REL)
        module, problems = loader.load_plugin(path)
        self.assertEqual(problems, [])
        self.assertEqual(loader.validate_contract_plugin(module), [])
        sha = loader.sha256_file(path)
        registry = PluginRegistry.objects.create(
            kind='CONTRACT', key=PLUGIN_KEY, version='1.0.0', sha256=sha,
            name='原料采购合同', file_name='contract_yuancailiaocaigouhetong.py',
            file_path=PLUGIN_REL)
        package = Package.objects.create(
            competition=self.competition, file_name='test.zip',
            status=Package.Status.SUCCESS)
        PackagePlugin.objects.create(
            package=package, plugin=registry, kind='CONTRACT',
            key=PLUGIN_KEY, version='1.0.0')

    def _create(self, rows, name='原料采购'):
        return engine.create_contract(
            contract_type_key=PLUGIN_KEY,
            plugin_version='1.0.0',
            name=name,
            parties=[
                {'role': '买方', 'companyId': self.buyer.id},
                {'role': '卖方', 'companyId': self.seller.id},
            ],
            inputs={'原料清单': rows},
            user=self.user,
        )

    def _value(self, company, key):
        ctx.set_competition_context(self.cid, ALIAS)
        row = CompanyFieldValue.objects.filter(company=company, field_key=key).first()
        return row.value if row else None

    def test_apply_moves_stock_and_cash(self):
        contract = self._create([
            {'item': '铁', 'quantity': 10, 'unitPrice': 5},
            {'item': '铜', 'quantity': 2, 'unitPrice': 20},
        ])
        engine.submit_contract(contract, user=self.user)
        contract.refresh_from_db()
        engine.confirm_party(contract, user=self.user)
        engine.confirm_party(contract, user=self.user)  # 双方确认后自动落账

        self.assertEqual(self._value(self.seller, 'yuanliaokucun'), {'铁': 90, '铜': 3})
        self.assertEqual(self._value(self.buyer, 'yuanliaokucun'), {'铁': 10, '铜': 2})
        self.assertEqual(self._value(self.buyer, 'yinhangzhanghu'), 910)  # 1000 - 90
        self.assertEqual(self._value(self.seller, 'yinhangzhanghu'), 90)

    def test_check_blocks_when_stock_short(self):
        contract = self._create([{'item': '铜', 'quantity': 999, 'unitPrice': 1}])
        with self.assertRaises(engine.ContractError) as caught:
            engine.submit_contract(contract, user=self.user)
        self.assertIn('库存不足', str(caught.exception))

    def test_check_blocks_when_cash_short(self):
        contract = self._create([{'item': '铁', 'quantity': 100, 'unitPrice': 100}])
        with self.assertRaises(engine.ContractError) as caught:
            engine.submit_contract(contract, user=self.user)
        self.assertIn('资金不足', str(caught.exception))

    def test_unknown_material_rejected(self):
        with self.assertRaises(engine.ContractError) as caught:
            self._create([{'item': '稀有矿', 'quantity': 1, 'unitPrice': 1}])
        self.assertIn('不存在', str(caught.exception))

    def test_empty_list_rejected(self):
        with self.assertRaises(engine.ContractError) as caught:
            self._create([])
        self.assertIn('原料清单', str(caught.exception))
