"""站内信图片白名单收窄测试（Decision 2.4 / 消息图片前缀）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class MessageImageWhitelistTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.sender = get_user_model().objects.create_user(
            username='wsender', password='x' * 12, email='wsender@test.local')
        self.receiver = get_user_model().objects.create_user(
            username='wreceiver', password='x' * 12, email='wreceiver@test.local')
        self.client = APIClient()
        self.client.force_authenticate(self.sender)

    def _send(self, images):
        return self.client.post('/api/messages/send', {
            'title': '图', 'body': '正文',
            'recipientUserIds': [self.receiver.id], 'images': images,
        }, format='json')

    def test_reject_non_messages_prefix(self):
        for bad in (
            '/api/files/view/uploads/a.png',
            '/api/files/view/map_backgrounds/1/bg.png',
            '/api/files/view/plugins/x.png',
            '/api/files/view/packages/x.png',
        ):
            with self.subTest(bad=bad):
                resp = self._send([bad])
                self.assertEqual(resp.status_code, 400, f'{bad}')
                self.assertIn('非法', resp.json()['message'])

    def test_accept_messages_prefix(self):
        resp = self._send(['/api/files/view/messages/2026/10/pic.png'])
        self.assertEqual(resp.status_code, 201, resp.content)
