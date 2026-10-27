"""学校 API 测试：读公开、写仅系统超管；新建/改名唯一性；删除不清账号。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.global_.schools.models import School

User = get_user_model()


class SchoolApiTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.admin = User.objects.create_user(
            username='sadmin', password='x' * 12, email='sadmin@test.local', is_superuser=True)
        self.player = User.objects.create_user(
            username='splayer', password='x' * 12, email='splayer@test.local')
        self.client = APIClient()

    def _as(self, user):
        self.client.force_authenticate(user)

    # ------------------------------------------------------------ 读

    def test_list_is_public(self):
        School.objects.create(name='公开中学', region='华东')
        resp = self.client.get('/api/schools')  # 未登录（注册页要用）
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([s['name'] for s in resp.json()], ['公开中学'])

    def test_search_filters_by_name(self):
        School.objects.create(name='第一中学')
        School.objects.create(name='第二小学')
        resp = self.client.get('/api/schools', {'q': '中学'})
        self.assertEqual([s['name'] for s in resp.json()], ['第一中学'])

    # ------------------------------------------------------------ 写权限

    def test_create_requires_superuser(self):
        self._as(self.player)
        resp = self.client.post('/api/schools', {'name': '无权中学'}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(School.objects.filter(name='无权中学').exists())

    def test_update_and_delete_require_superuser(self):
        school = School.objects.create(name='受保护中学')
        self._as(self.player)
        self.assertEqual(
            self.client.patch(f'/api/schools/{school.id}', {'name': '改名'}, format='json').status_code,
            403)
        self.assertEqual(self.client.delete(f'/api/schools/{school.id}').status_code, 403)
        self.assertTrue(School.objects.filter(pk=school.id).exists())

    # ------------------------------------------------------------ 增删改

    def test_create_school(self):
        self._as(self.admin)
        resp = self.client.post('/api/schools', {'name': '新建中学', 'region': '华北'}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['name'], '新建中学')
        self.assertEqual(body['region'], '华北')
        self.assertTrue(School.objects.filter(pk=body['id']).exists())

    def test_create_rejects_blank_and_duplicate(self):
        self._as(self.admin)
        self.assertEqual(
            self.client.post('/api/schools', {'name': '  '}, format='json').status_code, 400)
        School.objects.create(name='已存在中学')
        resp = self.client.post('/api/schools', {'name': '已存在中学'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('已存在', resp.json()['message'])
        self.assertEqual(School.objects.filter(name='已存在中学').count(), 1)

    def test_patch_renames_and_rejects_duplicate(self):
        school = School.objects.create(name='原名中学')
        School.objects.create(name='占用中学')
        self._as(self.admin)

        resp = self.client.patch(
            f'/api/schools/{school.id}', {'name': '新名中学', 'region': '华南'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        school.refresh_from_db()
        self.assertEqual(school.name, '新名中学')
        self.assertEqual(school.region, '华南')

        resp = self.client.patch(f'/api/schools/{school.id}', {'name': '占用中学'}, format='json')
        self.assertEqual(resp.status_code, 400)
        school.refresh_from_db()
        self.assertEqual(school.name, '新名中学')

    def test_patch_same_name_is_allowed(self):
        """名称未变时不应被判重复（排除自身）。"""
        school = School.objects.create(name='稳定中学')
        self._as(self.admin)
        resp = self.client.patch(
            f'/api/schools/{school.id}', {'name': '稳定中学', 'region': '西南'}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        school.refresh_from_db()
        self.assertEqual(school.region, '西南')

    def test_delete_keeps_users_and_clears_school(self):
        school = School.objects.create(name='待删中学')
        member = User.objects.create_user(
            username='smember', password='x' * 12, email='smember@test.local', school=school)
        self._as(self.admin)
        resp = self.client.delete(f'/api/schools/{school.id}')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(School.objects.filter(pk=school.id).exists())
        member.refresh_from_db()
        self.assertIsNone(member.school_id)  # 账号保留，学校置空（SET_NULL）

    def test_missing_school_404(self):
        self._as(self.admin)
        self.assertEqual(self.client.get('/api/schools/999999').status_code, 404)
        self.assertEqual(
            self.client.patch('/api/schools/999999', {'name': 'x'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete('/api/schools/999999').status_code, 404)
