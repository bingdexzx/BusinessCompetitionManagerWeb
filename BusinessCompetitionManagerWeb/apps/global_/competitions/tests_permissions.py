"""角色权限矩阵（2026-11）：不新增角色，只配置参赛代表 / 管理员能看什么、能操作什么。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.contracts.models import Contract
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class PermissionMatrixTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='权限矩阵赛', code='PERM', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.company = Company.objects.create(name='权限公司')
        self.root = User.objects.create_user(
            username='perm_root', password='x' * 12, email='perm_root@test.local',
            is_superuser=True)
        self.player = User.objects.create_user(
            username='perm_player', password='x' * 12, email='perm_player@test.local')
        self.admin = User.objects.create_user(
            username='perm_admin', password='x' * 12, email='perm_admin@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        CompetitionMembership.objects.create(
            user=self.admin, competition=self.competition,
            identity=CompetitionMembership.Identity.ADMIN,
            managed_companies=[self.company.id])
        Contract.objects.create(
            contract_type_key='purchase', name='权限合同',
            status=Contract.Status.DRAFT,
            parties=[{'role': 'buyer', 'companyId': self.company.id, 'confirmOrder': 0}],
            inputs={}, unified_number='PERM-FY0-00001', round_no=0,
            created_by=self.admin.id)
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def _matrix_url(self):
        return f'/api/competitions/{self.cid}/permissions'

    def test_get_returns_catalog_and_defaults(self):
        response = self.client.get(self._matrix_url(), HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIn('capabilities', body)
        self.assertIn('PLAYER', body['matrix'])
        self.assertIn('view.contracts', body['matrix']['PLAYER'])

    def test_put_saves_matrix_and_applies(self):
        matrix = {
            'PLAYER': ['view.companies'],
            'ADMIN': ['view.companies', 'view.contracts', 'act.companies'],
        }
        response = self.client.put(self._matrix_url(), {'matrix': matrix},
                                   format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)

        player_client = APIClient()
        player_client.force_authenticate(self.player)
        # 参赛代表失去「查看合同」→ 合同列表 403
        response = player_client.get(
            f'/api/competitions/{self.cid}/contracts', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 403)
        # 但仍能看合同以外的接口（这里用比赛详情近似）
        self.assertEqual(
            player_client.get(f'/api/competitions/{self.cid}', HTTP_HOST='127.0.0.1').status_code,
            200)

    def test_admin_can_gain_field_log_permission(self):
        admin_client = APIClient()
        admin_client.force_authenticate(self.admin)
        response = admin_client.get(
            f'/api/competitions/{self.cid}/logs/fields', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 403)

        self.client.put(self._matrix_url(), {'matrix': {
            'PLAYER': ['view.companies'],
            'ADMIN': ['view.companies', 'view.contracts', 'view.fieldlogs'],
        }}, format='json', HTTP_HOST='127.0.0.1')
        ctx.set_competition_context(self.cid, ALIAS)
        response = admin_client.get(
            f'/api/competitions/{self.cid}/logs/fields', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200, response.content)

    def test_matrix_rejects_unknown_capability(self):
        response = self.client.put(
            self._matrix_url(), {'matrix': {'PLAYER': ['view.unknown']}},
            format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 400)

    def test_non_superuser_cannot_save(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.put(
            self._matrix_url(), {'matrix': {'PLAYER': ['view.companies']}},
            format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 403)

    def test_superuser_always_allowed(self):
        self.client.put(self._matrix_url(), {'matrix': {'PLAYER': [], 'ADMIN': []}},
                        format='json', HTTP_HOST='127.0.0.1')
        ctx.set_competition_context(self.cid, ALIAS)
        response = self.client.get(
            f'/api/competitions/{self.cid}/contracts', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 200)
