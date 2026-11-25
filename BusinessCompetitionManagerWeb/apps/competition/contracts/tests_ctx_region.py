"""合同插件把城市节点换成区域名（2026-11）：ctx.region_of / node_region_map。"""

from django.test import TestCase

from apps.common import context as ctx
from apps.competition.basedata.models import MapNode, MapNodeType
from apps.competition.companies.models import Company
from apps.competition.contracts.dryrun import dry_run_contract_plugin
from apps.competition.contracts.models import Contract
from apps.global_.competitions.models import Competition
from plugins_runtime.api import ContractContext, Effect
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)


class _RegionModule:
    CONTRACT_KEY = 'city_deal'
    PARTY_ROLES = [{'role': 'buyer', 'label': '买方'}]
    INPUT_SCHEMA = [{'key': 'city', 'label': '城市', 'type': 'TEXT'}]

    @staticmethod
    def check(context):
        if not context.region_of(context.input('city')):
            return ['该城市没有归属区域']
        return []

    @staticmethod
    def apply(context):
        return [Effect(company='buyer', field='market_capacity', op='ADD', value=10,
                       region=context.region_of(context.input('city')))]


class _CityModule:
    """把「车站/矿点」输入换成所属城市，再换成该城市所在区域。"""

    CONTRACT_KEY = 'city_deal'
    PARTY_ROLES = [{'role': 'buyer', 'label': '买方'}]
    INPUT_SCHEMA = [{'key': 'node', 'label': '节点', 'type': 'TEXT'}]

    @staticmethod
    def check(context):
        if not context.city_of(context.input('node')):
            return ['该节点没有归属城市']
        return []

    @staticmethod
    def apply(context):
        city = context.city_of(context.input('node'))
        return [Effect(company='buyer', field='market_capacity', op='ADD', value=5,
                       region=context.region_of(city))]


class ContractContextRegionTests(TestCase):
    databases = {'default', ALIAS}

    def test_city_of_by_name_and_id(self):
        context = ContractContext(
            node_regions={'松平': '长平省', '#3': '长平省'},
            node_cities={'松平南': '松平', '#9': '松平', '松平': '松平'})
        self.assertEqual(context.city_of('松平南'), '松平')
        self.assertEqual(context.city_of(' 松平南 '), '松平')
        self.assertEqual(context.city_of_node(9), '松平')
        self.assertEqual(context.city_of('不存在'), '')
        self.assertEqual(context.city_of('不存在', '默认城'), '默认城')
        # 城市 → 区域 串联
        self.assertEqual(context.region_of(context.city_of('松平南')), '长平省')
        self.assertEqual(context.node_city_map(), {'松平南': '松平', '松平': '松平'})

    def test_region_of_by_name_and_id(self):
        context = ContractContext(node_regions={'上海': '华东', '#7': '华南'})
        self.assertEqual(context.region_of('上海'), '华东')
        self.assertEqual(context.region_of(' 上海 '), '华东')
        self.assertEqual(context.region_of_node(7), '华南')
        self.assertEqual(context.region_of('不存在'), '')
        self.assertEqual(context.region_of(None), '')
        self.assertEqual(context.region_of('不存在', '默认区'), '默认区')
        self.assertEqual(context.node_region_map(), {'上海': '华东'})


class PluginCityToRegionTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='城市换区域赛', code='CITY', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        node_type = MapNodeType.objects.create(name='城市点位')
        MapNode.objects.create(name='上海', region='华东', node_type=node_type, x=0, y=0)
        MapNode.objects.create(name='广州', region='华南', node_type=node_type, x=10, y=0)
        other_type = MapNodeType.objects.create(name='默认节点')
        MapNode.objects.create(name='无名', region='', node_type=other_type, x=5, y=5)
        Company.objects.create(name='买方公司')

    def test_context_built_by_engine_has_node_regions(self):
        from apps.competition.contracts import engine

        contract = Contract.objects.create(
            contract_type_key='city_deal', name='城市合同',
            status=Contract.Status.PENDING_EXEC,
            parties=[{'role': 'buyer', 'companyId': Company.objects.first().id,
                      'confirmOrder': 0}],
            inputs={'city': '上海'}, unified_number='CITY-FY0-00001', round_no=0,
            created_by=1)
        context = engine.build_context(contract)
        self.assertEqual(context.region_of('上海'), '华东')
        self.assertEqual(context.region_of('广州'), '华南')
        self.assertEqual(context.region_of('无名'), '')
        # 节点 → 城市（城市点位自己也算自己的城市）
        self.assertEqual(context.city_of('上海'), '上海')
        self.assertEqual(context.city_of('无名'), '')

    def test_dry_run_uses_node_regions(self):
        from unittest import mock

        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_RegionModule):
            result = dry_run_contract_plugin(
                contract_type_key='city_deal', inputs={'city': '广州'})
        self.assertEqual(result['problems'], [])
        self.assertEqual(result['effects'][0]['region'], '华南')

    def test_dry_run_uses_node_city_then_region(self):
        from unittest import mock

        node_type = MapNodeType.objects.get(name='城市点位')
        MapNode.objects.create(name='上海南', region='华东', node_type=node_type, x=1, y=1)
        # 车站节点：上海南 → 城市「上海」，但没有 city 字段，先归一次城市
        from apps.competition.regions import city_nodes

        city_nodes.assign_nodes_to_cities()

        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_CityModule):
            result = dry_run_contract_plugin(
                contract_type_key='city_deal', inputs={'node': '上海南'})
        self.assertEqual(result['effects'][0]['region'], '华东')

    def test_dry_run_reports_problem_for_unknown_city(self):
        from unittest import mock

        with mock.patch('apps.competition.contracts.dryrun.contract_module_for',
                        return_value=_RegionModule):
            result = dry_run_contract_plugin(
                contract_type_key='city_deal', inputs={'city': '火星'})
        self.assertEqual(result['problems'], ['该城市没有归属区域'])
