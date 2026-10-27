"""区域 / 消费者需求 / 总览卡片 测试。

比赛域模型走多库路由，测试需显式声明 `databases`（Django 会为 comp_unittest
自动建/毁 test 库并按路由迁移比赛域表）。alias 在导入期注册：系统检查阶段
（run_checks 早于 setUpClass）就要能解析到该连接。

注意：事务回滚不重置 Postgres 序列，Competition 主键跨测试会递增，
URL 一律用 self.cid 拼接，不能写死 /competitions/1/。
"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.regions.models import ConsumerDemand, Region
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)  # 导入期注册，供系统检查与测试运行器建 test 库


class RegionsApiTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth import get_user_model

        ctx.set_competition_context(1, ALIAS)
        self.competition = Competition.objects.create(
            name='区域测试赛', code='RG', db_name=ALIAS)
        self.cid = self.competition.pk
        self.manager = get_user_model().objects.create_user(
            username='mgr', password='x' * 12, email='mgr@test.local')
        CompetitionMembership.objects.create(
            user=self.manager, competition=self.competition,
            identity=CompetitionMembership.Identity.COMP_SUPER_ADMIN)
        self.player = get_user_model().objects.create_user(
            username='player', password='x' * 12, email='player@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def _url(self, suffix: str) -> str:
        return f'/api/competitions/{self.cid}{suffix}'

    # ------------------------------------------------------------ 区域

    def test_region_crud_and_unique_name(self):
        resp = self.client.post(self._url('/regions'),
                                {'name': '华东', 'description': 'd'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        region_id = resp.json()['id']

        resp = self.client.post(self._url('/regions'), {'name': '华东'}, format='json')
        self.assertEqual(resp.status_code, 400)  # 名称唯一

        resp = self.client.patch(self._url(f'/regions/{region_id}'),
                                 {'name': '华东大区'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['name'], '华东大区')

        resp = self.client.get(self._url('/regions'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

        resp = self.client.delete(self._url(f'/regions/{region_id}'))
        self.assertEqual(resp.status_code, 200)
        ctx.set_competition_context(self.cid, ALIAS)  # 请求会清空线程上下文
        self.assertFalse(Region.objects.filter(pk=region_id).exists())

    def test_overview_cards_roundtrip(self):
        region = Region.objects.create(name='华南')
        cards = [{'id': 1, 'displayName': 'GDP', 'companyId': 7, 'industryFieldId': 3, 'zone': 'top'}]
        resp = self.client.put(self._url(f'/regions/{region.id}/overview-cards'),
                               cards, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        region.refresh_from_db()
        # 字段键归一化：industryFieldId 补出规范键 industryFieldKey（旧键保留，兼容迁移）
        self.assertEqual(region.overview_cards[0]['industryFieldKey'], 3)
        self.assertEqual(region.overview_cards[0]['industryFieldId'], 3)

        resp = self.client.get(self._url(f'/regions/{region.id}/overview-cards'))
        self.assertEqual(resp.json()[0]['industryFieldKey'], 3)

        resp = self.client.put(self._url(f'/regions/{region.id}/overview-cards'),
                               [{'bad': True}], format='json')
        self.assertEqual(resp.status_code, 400)  # 缺 displayName

    # ------------------------------------------------------------ 消费者需求

    def test_demand_crud_and_filter(self):
        region_a = Region.objects.create(name='A')
        region_b = Region.objects.create(name='B')
        resp = self.client.post(self._url('/consumer-demands'),
                                {'regionId': region_a.id, 'quantity': 5, 'note': 'n'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        demand_id = resp.json()['id']
        self.assertEqual(resp.json()['quantity'], 5)

        self.client.post(self._url('/consumer-demands'),
                         {'regionId': region_b.id, 'quantity': 1}, format='json')
        resp = self.client.get(self._url(f'/consumer-demands?regionId={region_a.id}'))
        self.assertEqual(len(resp.json()), 1)

        resp = self.client.patch(self._url(f'/consumer-demands/{demand_id}'),
                                 {'quantity': 9}, format='json')
        self.assertEqual(resp.json()['quantity'], 9)

        resp = self.client.delete(self._url(f'/consumer-demands/{demand_id}'))
        self.assertEqual(resp.status_code, 200)
        ctx.set_competition_context(self.cid, ALIAS)
        self.assertFalse(ConsumerDemand.objects.filter(pk=demand_id).exists())

    def test_demand_triggers_formula_recompute(self):
        """公式可引用 consumerDemand 特殊键：需求变更 → 该区域公司字段重算。"""
        region = Region.objects.create(name='R')
        IndustryField.objects.create(
            field_key='demandScore', name='需求分',
            formula='consumerDemand * 2', is_calculated=True,
            data_table=IndustryField.DataTable.ENTITY)
        company = Company.objects.create(name='C1', region_id=region.id)

        resp = self.client.post(self._url('/consumer-demands'),
                                {'regionId': region.id, 'quantity': 5}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        row = CompanyFieldValue.objects.get(company=company, field_key='demandScore',
                                            fiscal_year__isnull=True)
        self.assertEqual(float(row.value), 10.0)

        # 需求增至 7 → 重算后 14
        demand = ConsumerDemand.objects.get(region=region)
        self.client.patch(self._url(f'/consumer-demands/{demand.id}'),
                          {'quantity': 7}, format='json')
        ctx.set_competition_context(self.cid, ALIAS)
        row.refresh_from_db()
        self.assertEqual(float(row.value), 14.0)

    # ------------------------------------------------------------ 权限

    def test_write_requires_competition_super_admin(self):
        self.client.force_authenticate(self.player)
        resp = self.client.post(self._url('/regions'), {'name': 'X'}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        resp = self.client.post(self._url('/consumer-demands'),
                                {'regionId': 1, 'quantity': 1}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)
        # 读仍允许（本比赛成员）
        self.assertEqual(self.client.get(self._url('/regions')).status_code, 200)
