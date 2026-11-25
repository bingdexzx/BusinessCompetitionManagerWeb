"""更新日志：超管发布，用户按最新 ID 只弹一次。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.global_.accounts.models import UpdateLog


class UpdateLogApiTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username='upd_admin', password='x' * 12, email='upd_admin@test.local',
            is_superuser=True)
        self.user = get_user_model().objects.create_user(
            username='upd_user', password='x' * 12, email='upd_user@test.local')
        self.client = APIClient()

    def _create(self, version='2026.11.23', title='更新测试', content='- 新增功能'):
        self.client.force_authenticate(self.admin)
        return self.client.post(
            '/api/update-logs',
            {'version': version, 'title': title, 'content': content},
            format='json',
        )

    def test_publish_and_read_once(self):
        response = self._create()
        self.assertEqual(response.status_code, 201, response.content)
        log_id = response.json()['id']
        # 发布人默认已读
        self.assertEqual(
            self.client.get('/api/update-logs/latest').json()['shouldShow'], False)

        self.client.force_authenticate(self.user)
        latest = self.client.get('/api/update-logs/latest').json()
        self.assertTrue(latest['shouldShow'])
        self.assertEqual(latest['log']['id'], log_id)

        read = self.client.post(f'/api/update-logs/{log_id}/read', {}, format='json')
        self.assertEqual(read.status_code, 200)
        after = self.client.get('/api/update-logs/latest').json()
        self.assertFalse(after['shouldShow'])

        second = self._create(version='2026.11.24', title='第二次更新')
        self.assertEqual(second.status_code, 201)
        self.client.force_authenticate(self.user)
        self.assertTrue(self.client.get('/api/update-logs/latest').json()['shouldShow'])

    def test_only_superuser_can_publish(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            '/api/update-logs',
            {'version': 'v1', 'title': 'x', 'content': 'y'},
            format='json',
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertEqual(UpdateLog.objects.count(), 0)

    def test_duplicate_version_rejected(self):
        self.assertEqual(self._create().status_code, 201)
        duplicate = self._create(version='2026.11.23', title='重复')
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.json()['message'], '该版本号已存在')
