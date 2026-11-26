"""网络日志 keyset 分页：不再精确 COUNT，用 cursor 翻页。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.global_.logs.models import NetworkLog


class NetworkLogPaginationTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='log_admin', password='x' * 12, email='log@test.local')
        for index in range(5):
            NetworkLog.objects.create(
                trace_id=f't{index}', method='GET', path=f'/api/demo/{index}',
                status=200, duration_ms=index,
            )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_cursor_pages_do_not_overlap(self):
        first = self.client.get('/api/logs/network?limit=2').json()
        self.assertEqual(len(first['items']), 2)
        self.assertTrue(first['hasMore'])
        self.assertTrue(first['nextCursor'])

        second = self.client.get(
            f"/api/logs/network?limit=2&cursor={first['nextCursor']}").json()
        self.assertEqual(len(second['items']), 2)
        self.assertFalse(
            {row['id'] for row in first['items']} & {row['id'] for row in second['items']})

    def test_invalid_cursor_returns_400(self):
        response = self.client.get('/api/logs/network?cursor=not-base64')
        self.assertEqual(response.status_code, 400)
