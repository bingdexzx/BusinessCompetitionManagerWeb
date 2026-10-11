"""WebSocket 通知通道测试（§5.1 实时推送、§14.3 WebSocket 入网络日志）。"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from BusinessCompetitionManagerWeb.asgi import application

User = get_user_model()


class NotificationConsumerTests(TransactionTestCase):
    """连接鉴权 + 分组推送（跨线程读库，故用 TransactionTestCase）。"""

    def _token_for(self, user) -> str:
        refresh = RefreshToken.for_user(user)
        refresh['tv'] = user.token_version
        return str(refresh.access_token)

    def test_reject_without_token(self):
        async def run():
            communicator = WebsocketCommunicator(application, '/ws/notifications')
            connected, _code = await communicator.connect()
            self.assertFalse(connected)
            await communicator.disconnect()

        async_to_sync(run)()

    def test_reject_stale_token_version(self):
        user = User.objects.create_user(username='ws_user2', password='x' * 12)
        token = self._token_for(user)
        user.bump_token_version()  # 顶号：旧 token 立即失效

        async def run():
            communicator = WebsocketCommunicator(
                application, f'/ws/notifications?token={token}')
            connected, _code = await communicator.connect()
            self.assertFalse(connected)
            await communicator.disconnect()

        async_to_connect = run
        async_to_sync(async_to_connect)()

    def test_push_reaches_subscribed_user(self):
        user = User.objects.create_user(username='ws_user3', password='x' * 12)
        token = self._token_for(user)

        async def run():
            communicator = WebsocketCommunicator(
                application, f'/ws/notifications?token={token}')
            connected, _code = await communicator.connect()
            self.assertTrue(connected)

            layer = get_channel_layer()
            await layer.group_send(
                f'user_{user.id}',
                {'type': 'user.notification',
                 'payload': {'type': 'notification', 'title': '测试提醒'}},
            )
            message = await communicator.receive_json_from(timeout=5)
            self.assertEqual(message.get('title'), '测试提醒')

            # 保活 ping
            await communicator.send_json_to({'type': 'ping'})
            pong = await communicator.receive_json_from(timeout=5)
            self.assertEqual(pong.get('type'), 'pong')
            await communicator.disconnect()

        async_to_sync(run)()
