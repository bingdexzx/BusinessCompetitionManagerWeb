"""区域/公司/财年 权限与数据语义补充测试（Decision 2 / 4 后端部分）。

多库：比赛域模型走 comp_unittest（导入期注册）；URL 一律用 self.cid 拼接。
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
register_competition_db(ALIAS)


class CompetitionSemanticsTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        from django.contrib.auth import get_user_model

        ctx.set_competition_context(1, ALIAS)
        self.competition = Competition.objects.create(
            name='语义测试赛', code='SM', db_name=ALIAS)
        self.cid = self.competition.pk

        User = get_user_model()
        self.manager = User.objects.create_user(
            username='smgr', password='x' * 12, email='smgr@test.local', is_superuser=True)
        CompetitionMembership.objects.create(
            user=self.manager, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN)
        self.player = User.objects.create_user(
            username='splayer', password='x' * 12, email='splayer@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.outsider = User.objects.create_user(
            username='sout', password='x' * 12, email='sout@test.local')

        self.manager_client = APIClient()
        self.manager_client.force_authenticate(self.manager)
        self.player_client = APIClient()
        self.player_client.force_authenticate(self.player)
        self.outsider_client = APIClient()
        self.outsider_client.force_authenticate(self.outsider)

    def _url(self, suffix: str) -> str:
        return f'/api/competitions/{self.cid}{suffix}'

    # -------------------------------------------------- Decision 2.1：读 = 成员

    def test_region_read_requires_member(self):
        region = Region.objects.create(name='华东')
        demand = ConsumerDemand.objects.create(region=region, quantity=2)
        urls = [
            self._url('/regions'),
            self._url(f'/regions/{region.id}'),
            self._url(f'/regions/{region.id}/overview-cards'),
            self._url('/consumer-demands'),
            self._url(f'/consumer-demands/{demand.id}'),
        ]
        for url in urls:
            with self.subTest(url=url):
                resp = self.outsider_client.get(url)
                self.assertEqual(resp.status_code, 403, resp.content)
                body = resp.json()
                self.assertEqual(body['code'], 403)
                self.assertTrue(body['message'])
                self.assertIn('details', body)
        # 成员仍可读
        self.assertEqual(self.player_client.get(self._url('/regions')).status_code, 200)

    def test_fiscal_read_requires_member(self):
        # 非成员读财年列表 / 备份快照 → 403（gate 先于查询，无需造财年数据）
        resp = self.outsider_client.get(self._url('/fiscal-years'))
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.json()['code'], 403)
        resp = self.outsider_client.get(self._url('/fiscal-years/1/backups'))
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertEqual(resp.json()['code'], 403)
        # 成员读财年列表 → 200（空列表）
        self.assertEqual(self.player_client.get(self._url('/fiscal-years')).status_code, 200)

    # -------------------------------------------------- Decision 4.4：字段键归一

    def test_overview_cards_normalize_industry_field_key(self):
        region = Region.objects.create(name='华南')
        cards = [{'id': 1, 'displayName': 'GDP', 'companyId': 7, 'industryFieldId': 3}]
        resp = self.manager_client.put(
            self._url(f'/regions/{region.id}/overview-cards'), cards, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()[0]['industryFieldKey'], 3)
        ctx.set_competition_context(self.cid, ALIAS)
        region.refresh_from_db()
        self.assertEqual(region.overview_cards[0]['industryFieldKey'], 3)

        # 已是 industryFieldKey 的保持不动
        cards2 = [{'id': 2, 'displayName': 'X', 'industryFieldKey': 9}]
        self.manager_client.put(
            self._url(f'/regions/{region.id}/overview-cards'), cards2, format='json')
        ctx.set_competition_context(self.cid, ALIAS)
        region.refresh_from_db()
        self.assertEqual(
            region.overview_cards[0], {'id': 2, 'displayName': 'X', 'industryFieldKey': 9})

    # ------------------------------------------- Decision 4.3：consumerDemand = 求和

    def test_consumer_demand_total_sums_quantity(self):
        region = Region.objects.create(name='R')
        IndustryField.objects.create(
            field_key='demandTotal', name='需求总量',
            formula='consumerDemand', is_calculated=True,
            data_table=IndustryField.DataTable.ENTITY)
        company = Company.objects.create(name='C1', region_id=region.id)
        ConsumerDemand.objects.create(region=region, quantity=3)
        ConsumerDemand.objects.create(region=region, quantity=4)

        # 通过 API 触发一次重算：consumerDemand = 该区域 quantity 求和（3+4+0）
        resp = self.manager_client.post(
            self._url('/consumer-demands'),
            {'regionId': region.id, 'quantity': 0}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        row = CompanyFieldValue.objects.get(
            company=company, field_key='demandTotal', fiscal_year__isnull=True)
        self.assertEqual(float(row.value), 7.0)

    # --------------------------------- Decision 4.1/4.2：公司 region FK + 删除 SET_NULL

    def test_company_region_endpoint_and_delete_set_null(self):
        region_a = Region.objects.create(name='A')
        region_b = Region.objects.create(name='B')
        company = Company.objects.create(name='C1', region_id=region_a.id)

        # 写权限：非管理 → 403
        resp = self.player_client.patch(
            self._url(f'/companies/{company.id}/region'),
            {'regionId': region_b.id}, format='json')
        self.assertEqual(resp.status_code, 403, resp.content)

        # 指派区域
        resp = self.manager_client.patch(
            self._url(f'/companies/{company.id}/region'),
            {'regionId': region_b.id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['regionId'], region_b.id)
        ctx.set_competition_context(self.cid, ALIAS)
        company.refresh_from_db()
        self.assertEqual(company.region_id, region_b.id)

        # 区域不存在 → 400
        resp = self.manager_client.patch(
            self._url(f'/companies/{company.id}/region'),
            {'regionId': 999999}, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)

        # 清除区域归属
        resp = self.manager_client.patch(
            self._url(f'/companies/{company.id}/region'),
            {'regionId': None}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.json()['regionId'])

        # 删除区域 → 公司 region SET_NULL，需求级联删除
        ctx.set_competition_context(self.cid, ALIAS)
        company.region = region_a
        company.save()
        ConsumerDemand.objects.create(region=region_a, quantity=1)
        resp = self.manager_client.delete(self._url(f'/regions/{region_a.id}'))
        self.assertEqual(resp.status_code, 200, resp.content)
        ctx.set_competition_context(self.cid, ALIAS)
        company.refresh_from_db()
        self.assertIsNone(company.region_id)
        self.assertFalse(ConsumerDemand.objects.filter(region_id=region_a.id).exists())
