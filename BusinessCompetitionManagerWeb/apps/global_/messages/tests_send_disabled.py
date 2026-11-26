"""消息中心只读：管理员与参赛选手均不可发信（2026-11 需求变更）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class SendDisabledTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.member = get_user_model().objects.create_user(
            username='msg_member', password='x' * 12, email='member@test.local')
        self.admin = get_user_model().objects.create_superuser(
            username='msg_admin', password='x' * 12, email='admin@test.local')
        self.receiver = get_user_model().objects.create_user(
            username='msg_receiver', password='x' * 12, email='receiver@test.local')
        self.client = APIClient()

    def _send(self):
        return self.client.post('/api/messages/send', {
            'title': '测试消息',
            'body': '正文',
            'recipientUserIds': [self.receiver.id],
        }, format='json')

    def test_participant_cannot_send(self):
        self.client.force_authenticate(self.member)
        resp = self._send()
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertIn('关闭发送', resp.json()['message'])

    def test_superuser_cannot_send(self):
        self.client.force_authenticate(self.admin)
        resp = self._send()
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_anonymous_cannot_send(self):
        resp = self._send()
        self.assertIn(resp.status_code, (401, 403))
