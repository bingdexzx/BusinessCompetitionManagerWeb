"""网络日志分页：offset + total（总数短缓存）。"""

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

    def test_offset_pages_do_not_overlap(self):
        first = self.client.get(
            '/api/logs/network?limit=2&offset=0&path=/api/demo').json()
        self.assertEqual(len(first['items']), 2)
        self.assertIn('total', first)

        second = self.client.get(
            '/api/logs/network?limit=2&offset=2&path=/api/demo').json()
        self.assertEqual(len(second['items']), 2)
        self.assertFalse(
            {row['id'] for row in first['items']} & {row['id'] for row in second['items']})

    def test_invalid_limit_falls_back(self):
        response = self.client.get('/api/logs/network?limit=abc')
        self.assertIn(response.status_code, (200, 400))
