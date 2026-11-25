"""区域总览（2026-10 需求：与旧系统一致）测试。

- 区域来自**地图管理**（`MapNode.region`）∪ 已有 Region 实体 → map-overview；
- 区域内的公司按**公司 location 字段值 == 该区域下某个地图节点名**匹配；
- 卡片值由服务端算好（优先最新财年，字段/公司缺失则 valid=False）；
- 按**区域名**保存卡片（无 Region 行时自动建）；消费者需求也可按区域名创建。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.basedata.models import MapNode, MapNodeType
from apps.competition.companies.models import Company
from apps.competition.fiscal.models import FiscalYear
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.regions.models import ConsumerDemand, Region
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class RegionOverviewTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='区域总览测试赛', code='RO', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.manager = User.objects.create_user(
            username='romgr', password='x' * 12, email='romgr@test.local', is_superuser=True)
        CompetitionMembership.objects.create(
            user=self.manager, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN)
        self.player = User.objects.create_user(
            username='roplayer', password='x' * 12, email='roplayer@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)

        # 地图节点（区域在**地图管理**里通过节点 region 字段产生）
        node_type = MapNodeType.objects.create(name='城市')
        MapNode.objects.create(name='北京', region='华北', node_type=node_type)
        MapNode.objects.create(name='上海', region='华东', node_type=node_type)

        # 产业字段：location（判定公司属于哪个区域）+ 产量（卡片绑定）
        self.location_field = IndustryField.objects.create(
            field_key='location', name='所在地', field_type='TEXT', plugin_key='manufacturer')
        self.output_field = IndustryField.objects.create(
            field_key='output', name='产量', field_type='NUMBER', plugin_key='manufacturer')

        self.company = Company.objects.create(name='华北公司', industry_key='manufacturer')
        CompanyFieldValue.objects.create(
            company=self.company, field_key='location', fiscal_year=None, value='北京', version=1)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='output', fiscal_year=None, value=120, version=1)
        self.other = Company.objects.create(name='无地点公司')

        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def _url(self, suffix: str) -> str:
        return f'/api/competitions/{self.cid}{suffix}'

    def _overview(self):
        ctx.set_competition_context(self.cid, ALIAS)
        resp = self.client.get(self._url('/regions/map-overview'))
        self.assertEqual(resp.status_code, 200, resp.content)
        return {row['region']: row for row in resp.json()}

    # ------------------------------------------------------------ 区域来自地图

    def test_regions_come_from_map_nodes(self):
        rows = self._overview()
        self.assertEqual(set(rows), {'华北', '华东'})  # 地图上有哪些区域名就展示哪些
        self.assertIsNone(rows['华北']['id'])          # 还没有 Region 行（未存卡片）
        self.assertEqual(rows['华北']['cards'], [])

    def test_region_entity_without_map_node_also_listed(self):
        Region.objects.create(name='华南')
        self.assertIn('华南', self._overview())

    def test_delete_region_blocked_while_map_nodes_use_it(self):
        """区域名下仍有地图节点时不允许删除（旧系统口径）。"""
        ctx.set_competition_context(self.cid, ALIAS)
        region = Region.objects.create(name='华北')  # 地图节点「北京」的 region = 华北
        resp = self.client.delete(self._url(f'/regions/{region.id}'))
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('地图节点', resp.json()['message'])
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertTrue(Region.objects.filter(pk=region.id).exists())

    def test_delete_region_without_nodes_allowed(self):
        ctx.set_competition_context(self.cid, ALIAS)
        region = Region.objects.create(name='无节点区域')
        resp = self.client.delete(self._url(f'/regions/{region.id}'))
        self.assertEqual(resp.status_code, 200, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertFalse(Region.objects.filter(pk=region.id).exists())

    # ------------------------------------------------------------ 区域内公司（location 口径）

    def test_companies_matched_by_location_field(self):
        rows = self._overview()
        self.assertEqual([c['name'] for c in rows['华北']['companies']], ['华北公司'])
        self.assertEqual(rows['华东']['companies'], [])  # 没有公司 location=上海
        self.assertEqual(rows['华北']['companies'][0]['industryKey'], 'manufacturer')

    def test_companies_need_matching_node_name(self):
        node_type = MapNodeType.objects.get(name='城市')
        MapNode.objects.create(name='华北公司', region='华东', node_type=node_type)
        # location='北京' 不等于华东区域下的节点名「华北公司」→ 仍不属于华东
        self.assertEqual(self._overview()['华东']['companies'], [])

    # ------------------------------------------------------------ 卡片与取值

    def test_save_cards_by_name_then_resolve_value(self):
        resp = self.client.put(
            self._url('/regions/by-name/华北/overview-cards'),
            {'cards': [{'id': 'c1', 'displayName': '产量', 'companyId': self.company.id,
                        'industryFieldId': self.output_field.id, 'zone': 'top'}]},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json(), {'success': True})
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertTrue(Region.objects.filter(name='华北').exists())  # 自动补建 Region 行

        row = self._overview()['华北']
        self.assertIsNotNone(row['id'])
        card = row['cards'][0]
        self.assertEqual(card['displayName'], '产量')
        self.assertEqual(card['zone'], 'top')
        self.assertEqual(card['value'], 120)
        self.assertTrue(card['valid'])
        self.assertEqual(card['fieldType'], 'NUMBER')

    def test_card_invalid_when_field_or_company_missing(self):
        resp = self.client.put(
            self._url('/regions/by-name/华北/overview-cards'),
            {'cards': [
                {'id': 'c1', 'displayName': '坏字段', 'companyId': self.company.id,
                 'industryFieldId': 999999, 'zone': 'bottom'},
                {'id': 'c2', 'displayName': '坏公司', 'companyId': 999999,
                 'industryFieldId': self.output_field.id, 'zone': 'bottom'},
            ]},
            format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        cards = self._overview()['华北']['cards']
        self.assertEqual([c['valid'] for c in cards], [False, False])
        self.assertEqual([c['value'] for c in cards], [None, None])

    def test_value_prefers_newest_fiscal_year(self):
        fy1 = FiscalYear.objects.create(year=1)
        fy2 = FiscalYear.objects.create(year=2)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='output', fiscal_year=fy1, value=10, version=1)
        CompanyFieldValue.objects.create(
            company=self.company, field_key='output', fiscal_year=fy2, value=77, version=1)
        self.client.put(
            self._url('/regions/by-name/华北/overview-cards'),
            {'cards': [{'id': 'c1', 'displayName': '产量', 'companyId': self.company.id,
                        'industryFieldId': self.output_field.id, 'zone': 'bottom'}]},
            format='json')
        self.assertEqual(self._overview()['华北']['cards'][0]['value'], 77)

    def test_save_cards_requires_manager(self):
        self.client.force_authenticate(self.player)
        resp = self.client.put(self._url('/regions/by-name/华北/overview-cards'),
                               {'cards': []}, format='json')
        self.assertEqual(resp.status_code, 403)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertFalse(Region.objects.filter(name='华北').exists())

    def test_map_overview_requires_member(self):
        outsider = User.objects.create_user(
            username='rooutsider', password='x' * 12, email='rooutsider@test.local')
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self._url('/regions/map-overview')).status_code, 403)

    # ------------------------------------------------------------ 消费者需求（按区域名）

    def test_demand_created_by_region_name(self):
        resp = self.client.post(self._url('/consumer-demands'), {
            'region': '华北', 'productId': None, 'productName': '钢材', 'quantity': 30, 'note': '备注',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['regionName'], '华北')
        self.assertEqual(body['quantity'], 30)

        ctx.set_competition_context(self.cid, ALIAS)
        self.assertEqual(ConsumerDemand.objects.count(), 1)
        self.assertEqual(ConsumerDemand.objects.first().region.name, '华北')

        listed = self.client.get(self._url('/consumer-demands')).json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['regionName'], '华北')
        self.assertEqual(listed[0]['productName'], '钢材')

    def test_demand_requires_region(self):
        resp = self.client.post(self._url('/consumer-demands'),
                                {'productName': 'x', 'quantity': 1}, format='json')
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------ 公司产业字段下拉

    def test_company_industry_fields_endpoint(self):
        resp = self.client.get(self._url(f'/companies/{self.company.id}/industry-fields'))
        self.assertEqual(resp.status_code, 200, resp.content)
        keys = [f['key'] for f in resp.json()]
        self.assertEqual(sorted(keys), ['location', 'output'])
        self.assertEqual(resp.json()[0]['name'], '所在地')

    def test_company_industry_fields_denied_for_outsider(self):
        outsider = User.objects.create_user(
            username='rooutsider2', password='x' * 12, email='rooutsider2@test.local')
        self.client.force_authenticate(outsider)
        resp = self.client.get(self._url(f'/companies/{self.company.id}/industry-fields'))
        self.assertEqual(resp.status_code, 403)
