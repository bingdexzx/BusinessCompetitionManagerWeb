"""消息图片透传测试（2026-10 缺口补齐：SendView 把 images 持久化进 Message.payload）。"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


class MessageImagesTests(TestCase):
    databases = {'default'}

    def setUp(self):
        self.sender = get_user_model().objects.create_user(
            username='img_sender', password='x' * 12, email='img_s@test.local')
        self.receiver = get_user_model().objects.create_user(
            username='img_receiver', password='x' * 12, email='img_r@test.local')
        self.client = APIClient()
        self.client.force_authenticate(self.sender)

    def _send(self, images):
        return self.client.post('/api/messages/send', {
            'title': '带图消息', 'body': '正文',
            'recipientUserIds': [self.receiver.id], 'images': images,
        }, format='json')

    def test_images_persisted_in_payload(self):
        images = [f'/api/files/view/messages/2026/10/pic{i}.png' for i in range(2)]
        resp = self._send(images)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['payload'].get('images'), images)

    def test_reject_more_than_nine(self):
        images = [f'/api/files/view/messages/x{i}.png' for i in range(10)]
        resp = self._send(images)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('9', resp.json()['message'])

    def test_reject_external_urls(self):
        resp = self._send(['https://evil.example.com/track.png'])
        self.assertEqual(resp.status_code, 400)
        self.assertIn('非法', resp.json()['message'])

    def test_no_images_still_ok(self):
        resp = self._send([])
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['payload'].get('images'), None)
