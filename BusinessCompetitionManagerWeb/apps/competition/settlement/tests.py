"""结算与获奖测试（2026-10 需求变更）：结算只算分；奖项人工设定 + 人工发放。

- 比赛域模型走多库路由：alias 在导入期注册，URL 用 self.cid 拼接
  （事务回滚不重置序列，pk 会漂移）；
- 个人奖 → 一个人档案一条；集体奖 → 所选公司对应队伍**全员**各一条；
- 撤销/删除奖项定义可回收档案记录。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.industries.models import CompanyFieldValue
from apps.competition.settlement.models import (
    AwardDefinition, AwardGrant, ScoringCriterion, SettlementRun,
)
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.profiles.models import AwardRecord, MedalAsset
from apps.global_.teams.models import Team, TeamMember
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class SettlementAwardTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='结算测试赛', code='ST', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)

        self.admin = User.objects.create_user(
            username='stadmin', password='x' * 12, email='stadmin@test.local', is_superuser=True)
        self.player = User.objects.create_user(
            username='stplayer', password='x' * 12, email='stplayer@test.local')
        self.mate = User.objects.create_user(
            username='stmate', password='x' * 12, email='stmate@test.local')
        self.outsider = User.objects.create_user(
            username='stoutsider', password='x' * 12, email='stoutsider@test.local')

        for user in (self.admin, self.player, self.mate):
            CompetitionMembership.objects.create(
                user=user, competition=self.competition,
                identity=CompetitionMembership.Identity.PLAYER)

        # 公司 + 队伍（一队一公司）：甲公司 → 队伍，含队长 + 1 名队员
        self.company = Company.objects.create(name='甲公司')
        self.team = Team.objects.create(
            competition=self.competition, name='甲队', captain=self.player,
            company_id=self.company.id)
        TeamMember.objects.create(team=self.team, user=self.player,
                                  role=TeamMember.Role.CAPTAIN)
        TeamMember.objects.create(team=self.team, user=self.mate,
                                  role=TeamMember.Role.MEMBER)
        self.company.team_id = self.team.id
        self.company.save(update_fields=['team_id'])

        # 无队伍公司（用于集体奖拒绝分支）
        self.lonely = Company.objects.create(name='乙公司')

        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def _url(self, suffix: str) -> str:
        return f'/api/competitions/{self.cid}{suffix}'

    def _refresh_ctx(self):
        ctx.set_competition_context(self.cid, ALIAS)

    def _make_company_with_revenue(self, name: str, revenue: float) -> Company:
        company = Company.objects.create(name=name)
        CompanyFieldValue.objects.create(
            company=company, field_key='revenue', fiscal_year=None, value=revenue, version=1)
        return company

    # ------------------------------------------------------------ 结算：只算分

    def test_settlement_only_computes_scores(self):
        """结算产出得分与名次，且**不再**自动评奖、不再写个人档案。"""
        ScoringCriterion.objects.create(name='营收', field_key='revenue', weight=1.0)
        self._make_company_with_revenue('低营收', 100)
        self._make_company_with_revenue('高营收', 300)

        resp = self.client.post(self._url('/settlement/run'))
        self.assertEqual(resp.status_code, 201, resp.content)
        self._refresh_ctx()

        run = SettlementRun.objects.get(pk=resp.json()['runId'])
        entries = run.result['entries']
        self.assertEqual(len(entries), 4)  # 含 setUp 里的甲/乙公司（营收缺失 → 0）
        by_name = {e['companyName']: e for e in entries}
        # min-max 归一：营收 0/0/100/300 → 低营收归一 1/3 → 33.33，高营收 1.0 → 100
        self.assertEqual(by_name['高营收']['score'], 100.0)
        self.assertAlmostEqual(by_name['低营收']['score'], 100 / 3, places=2)
        self.assertEqual(by_name['高营收']['rank'], 1)
        self.assertLess(by_name['高营收']['rank'], by_name['低营收']['rank'])
        self.assertLess(by_name['低营收']['rank'], by_name['甲公司']['rank'])
        self.assertNotIn('awardLevel', by_name['高营收'])

        # 关键：结算不再产生任何获奖记录
        self.assertEqual(AwardRecord.objects.count(), 0)

    def test_settlement_result_endpoint(self):
        ScoringCriterion.objects.create(name='营收', field_key='revenue', weight=1.0)
        self._make_company_with_revenue('唯一', 50)
        self.client.post(self._url('/settlement/run'))

        resp = self.client.get(self._url('/settlement/result'))
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertIsNotNone(body['run'])
        self.assertIn('criteria', body['run'])
        self.assertTrue(body['entries'])
        self.assertNotIn('awardLevel', body['entries'][0])

    # ------------------------------------------------------------ 奖项定义

    def test_award_definition_crud(self):
        resp = self.client.post(self._url('/settlement/config'), {
            'kind': 'award', 'name': '最佳CEO', 'awardKind': 'INDIVIDUAL',
            'medalLevel': '一等奖', 'description': '个人荣誉',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        award_id = resp.json()['id']

        resp = self.client.post(self._url('/settlement/config'), {
            'kind': 'award', 'name': '冠军团队', 'awardKind': 'COLLECTIVE',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)

        # 同类型同名重复 → 400；不同类型同名允许
        resp = self.client.post(self._url('/settlement/config'), {
            'kind': 'award', 'name': '最佳CEO', 'awardKind': 'INDIVIDUAL',
        }, format='json')
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(self._url('/settlement/config'), {
            'kind': 'award', 'name': '最佳CEO', 'awardKind': 'COLLECTIVE',
        }, format='json')
        self.assertEqual(resp.status_code, 201)

        resp = self.client.get(self._url('/settlement/config'))
        self.assertEqual(resp.status_code, 200)
        awards = resp.json()['awards']
        self.assertNotIn('awardRules', resp.json())
        self.assertEqual(len(awards), 3)
        best = next(a for a in awards if a['id'] == award_id)
        self.assertEqual(best['kind'], 'INDIVIDUAL')
        self.assertEqual(best['kindLabel'], '个人奖')
        self.assertEqual(best['medalLevel'], '一等奖')

        resp = self.client.delete(self._url(f'/settlement/config/award/{award_id}'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self._refresh_ctx()
        self.assertFalse(AwardDefinition.objects.filter(pk=award_id).exists())

    def test_invalid_award_kind_rejected(self):
        resp = self.client.post(self._url('/settlement/config'), {
            'kind': 'award', 'name': '怪奖', 'awardKind': 'TEAM',
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    # ------------------------------------------------------------ 个人奖发放

    def test_individual_grant_records_on_that_person_only(self):
        award = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL, medal_level='一等奖')
        resp = self.client.post(self._url('/awards/grants'), {
            'awardId': award.id, 'userId': self.player.id, 'note': '表现突出',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['recipientCount'], 1)
        self.assertEqual(body['recipients'], [
            {'userId': self.player.id, 'userName': self.player.username}])

        records = AwardRecord.objects.filter(competition_id=self.cid)
        self.assertEqual(records.count(), 1)
        record = records.first()
        self.assertEqual(record.user_id, self.player.id)
        self.assertEqual(record.award_name, '最佳CEO')
        self.assertEqual(record.award_kind, 'INDIVIDUAL')
        self.assertEqual(record.competition_name, '结算测试赛')
        self.assertEqual(record.detail.get('note'), '表现突出')
        # 配置了奖牌等级 → 自动挂上电子奖牌
        self.assertIsNotNone(record.medal_id)
        self.assertTrue(MedalAsset.objects.filter(award_level='一等奖').exists())
        # 没获奖的人不应有记录
        self.assertFalse(AwardRecord.objects.filter(user=self.mate).exists())

    # ------------------------------------------------------------ 集体奖发放

    def test_collective_grant_records_all_team_members(self):
        award = AwardDefinition.objects.create(
            name='冠军团队', kind=AwardDefinition.Kind.COLLECTIVE)
        resp = self.client.post(self._url('/awards/grants'), {
            'awardId': award.id, 'companyId': self.company.id,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['recipientCount'], 2)  # 队长 + 队员

        records = AwardRecord.objects.filter(competition_id=self.cid)
        self.assertEqual(
            sorted(records.values_list('user_id', flat=True)),
            sorted([self.player.id, self.mate.id]))
        for record in records:
            self.assertEqual(record.award_name, '冠军团队')
            self.assertEqual(record.award_kind, 'COLLECTIVE')
            self.assertEqual(record.team_name, '甲公司')  # 公司名记入档案

    def test_collective_grant_rejected_without_team(self):
        award = AwardDefinition.objects.create(
            name='冠军团队', kind=AwardDefinition.Kind.COLLECTIVE)
        resp = self.client.post(self._url('/awards/grants'), {
            'awardId': award.id, 'companyId': self.lonely.id,
        }, format='json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('队伍', resp.json()['message'])
        self.assertEqual(AwardRecord.objects.count(), 0)
        self._refresh_ctx()  # 请求会清空线程内的比赛上下文
        self.assertFalse(AwardGrant.objects.exists())

    def test_kind_must_match_recipient(self):
        individual = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL)
        collective = AwardDefinition.objects.create(
            name='冠军团队', kind=AwardDefinition.Kind.COLLECTIVE)
        # 个人奖给公司 → 400
        resp = self.client.post(self._url('/awards/grants'), {
            'awardId': individual.id, 'companyId': self.company.id}, format='json')
        self.assertEqual(resp.status_code, 400)
        # 个人奖不给人 → 400
        resp = self.client.post(self._url('/awards/grants'), {
            'awardId': individual.id}, format='json')
        self.assertEqual(resp.status_code, 400)
        # 集体奖给人 → 400
        resp = self.client.post(self._url('/awards/grants'), {
            'awardId': collective.id, 'userId': self.player.id}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_same_person_can_hold_multiple_awards(self):
        """同一人可获多个奖（个人奖 + 集体奖 + 多个奖项）。"""
        solo = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL)
        team_award = AwardDefinition.objects.create(
            name='冠军团队', kind=AwardDefinition.Kind.COLLECTIVE)
        self.client.post(self._url('/awards/grants'),
                         {'awardId': solo.id, 'userId': self.player.id}, format='json')
        self.client.post(self._url('/awards/grants'),
                         {'awardId': team_award.id, 'companyId': self.company.id}, format='json')
        self.client.post(self._url('/awards/grants'),
                         {'awardId': solo.id, 'userId': self.player.id}, format='json')

        mine = AwardRecord.objects.filter(user=self.player, competition_id=self.cid)
        self.assertEqual(mine.count(), 3)
        self.assertEqual(
            sorted(mine.values_list('award_name', flat=True)),
            ['冠军团队', '最佳CEO', '最佳CEO'])

    # ------------------------------------------------------------ 撤销

    def test_revoke_grant_removes_profile_records(self):
        award = AwardDefinition.objects.create(
            name='冠军团队', kind=AwardDefinition.Kind.COLLECTIVE)
        grant_id = self.client.post(self._url('/awards/grants'), {
            'awardId': award.id, 'companyId': self.company.id}, format='json').json()['id']
        self.assertEqual(AwardRecord.objects.count(), 2)

        resp = self.client.delete(self._url(f'/awards/grants/{grant_id}'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['removed'], 2)
        self.assertEqual(AwardRecord.objects.count(), 0)
        self._refresh_ctx()
        self.assertFalse(AwardGrant.objects.filter(pk=grant_id).exists())

    def test_delete_award_definition_revokes_its_grants(self):
        award = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL)
        self.client.post(self._url('/awards/grants'),
                         {'awardId': award.id, 'userId': self.player.id}, format='json')
        self.assertEqual(AwardRecord.objects.count(), 1)

        resp = self.client.delete(self._url(f'/settlement/config/award/{award.id}'))
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['revokedRecords'], 1)
        self.assertEqual(AwardRecord.objects.count(), 0)

    def test_grants_listing(self):
        individual = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL)
        collective = AwardDefinition.objects.create(
            name='冠军团队', kind=AwardDefinition.Kind.COLLECTIVE, medal_level='二等奖')
        self.client.post(self._url('/awards/grants'),
                         {'awardId': individual.id, 'userId': self.player.id}, format='json')
        self.client.post(self._url('/awards/grants'),
                         {'awardId': collective.id, 'companyId': self.company.id}, format='json')

        resp = self.client.get(self._url('/awards/grants'))
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        self.assertEqual(len(rows), 2)
        by_award = {r['awardName']: r for r in rows}
        self.assertEqual(by_award['最佳CEO']['kindLabel'], '个人奖')
        self.assertEqual(by_award['最佳CEO']['userName'], self.player.username)
        self.assertEqual(by_award['冠军团队']['recipientCount'], 2)
        self.assertEqual(by_award['冠军团队']['companyName'], '甲公司')
        self.assertEqual(by_award['冠军团队']['medalLevel'], '二等奖')
        self.assertEqual(by_award['冠军团队']['grantedByUsername'], self.admin.username)

    # ------------------------------------------------------------ 候选人 / 权限

    def test_candidates_lists_competition_members(self):
        resp = self.client.get(self._url('/settlement/candidates'))
        self.assertEqual(resp.status_code, 200, resp.content)
        usernames = {c['username'] for c in resp.json()}
        self.assertIn('stplayer', usernames)
        self.assertNotIn('stoutsider', usernames)  # 非本比赛成员

        # 带所属公司 + 关键字搜索
        resp = self.client.get(self._url('/settlement/candidates'), {'q': 'stplayer'})
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['companyName'], '甲公司')
        self.assertEqual(rows[0]['companyId'], self.company.id)

    def test_awards_are_manager_only(self):
        award = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL)
        self.client.force_authenticate(self.player)
        self.assertEqual(self.client.get(self._url('/settlement/config')).status_code, 403)
        self.assertEqual(self.client.get(self._url('/settlement/candidates')).status_code, 403)
        self.assertEqual(self.client.get(self._url('/awards/grants')).status_code, 403)
        self.assertEqual(
            self.client.post(self._url('/awards/grants'),
                             {'awardId': award.id, 'userId': self.player.id},
                             format='json').status_code, 403)
        self.assertEqual(self.client.post(self._url('/settlement/run')).status_code, 403)
        self.assertEqual(AwardRecord.objects.count(), 0)

    def test_my_awards_exposes_manual_fields(self):
        """个人档案接口返回奖项名称/类型（本人可见）。"""
        award = AwardDefinition.objects.create(
            name='最佳CEO', kind=AwardDefinition.Kind.INDIVIDUAL)
        self.client.post(self._url('/awards/grants'),
                         {'awardId': award.id, 'userId': self.player.id}, format='json')

        self.client.force_authenticate(self.player)
        resp = self.client.get('/api/me/awards')
        self.assertEqual(resp.status_code, 200, resp.content)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['awardName'], '最佳CEO')
        self.assertEqual(rows[0]['awardKind'], 'INDIVIDUAL')
        self.assertEqual(rows[0]['awardKindLabel'], '个人奖')
        self.assertEqual(rows[0]['competitionName'], '结算测试赛')
