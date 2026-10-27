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

    def test_resource_changed_subscribe_and_replay(self):
        """资源变更广播：订阅 comp_<cid> 分组 → 收 resource:changed；lastSeq 断线重放。"""
        from asgiref.sync import sync_to_async

        from apps.common.broadcast import emit_resource_changed

        user = User.objects.create_user(
            username='ws_user4', password='x' * 12, is_superuser=True)
        token = self._token_for(user)

        async def run():
            communicator = WebsocketCommunicator(
                application, f'/ws/notifications?token={token}')
            connected, _code = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to({'type': 'subscribe', 'competitionId': 42})
            ack = await communicator.receive_json_from(timeout=5)
            self.assertEqual(ack.get('type'), 'resource:subscribed')

            layer = get_channel_layer()
            await layer.group_send(
                'comp_42',
                {'type': 'resource.changed', 'seq': 7, 'resource': 'contracts',
                 'action': 'created', 'competitionId': 42,
                 'payload': {'id': 1}, 'ts': 'now'})
            event = await communicator.receive_json_from(timeout=5)
            self.assertEqual(event.get('type'), 'resource:changed')
            self.assertEqual(event.get('seq'), 7)
            self.assertEqual(event.get('resource'), 'contracts')

            # 断线重放：流水补两条，带 lastSeq=第一条的 seq 只补发其后的事件
            seq_a = await sync_to_async(emit_resource_changed)(
                42, 'contracts', 'created', {'id': 1})
            seq_b = await sync_to_async(emit_resource_changed)(
                42, 'contracts', 'updated', {'id': 1})
            self.assertIsNotNone(seq_a)
            self.assertGreater(seq_b, seq_a)
            await communicator.send_json_to(
                {'type': 'replay', 'competitionId': 42, 'lastSeq': seq_a})
            replay = await communicator.receive_json_from(timeout=5)
            self.assertEqual(replay.get('type'), 'resource:replay')
            seqs = [e.get('seq') for e in replay.get('events', [])]
            self.assertIn(seq_b, seqs)
            self.assertNotIn(seq_a, seqs)  # 增量：lastSeq 之前的不重放
            await communicator.disconnect()

        async_to_sync(run)()

    def test_global_scope_subscribe_and_replay(self):
        """系统级资源：连接即入 global 组；scope=global 订阅回执 + 断线 seq 重放。"""
        from asgiref.sync import sync_to_async

        from apps.common.broadcast import emit_resource_changed

        user = User.objects.create_user(username='ws_user5', password='x' * 12)
        token = self._token_for(user)

        async def run():
            communicator = WebsocketCommunicator(
                application, f'/ws/notifications?token={token}')
            connected, _code = await communicator.connect()
            self.assertTrue(connected)

            # 无需额外鉴权即可订阅系统级作用域（连接时已入 global 组）
            await communicator.send_json_to({'type': 'subscribe', 'scope': 'global'})
            ack = await communicator.receive_json_from(timeout=5)
            self.assertEqual(ack.get('type'), 'resource:subscribed')
            self.assertEqual(ack.get('scope'), 'global')

            layer = get_channel_layer()
            await layer.group_send(
                'global',
                {'type': 'resource.changed', 'seq': 11, 'resource': 'users',
                 'action': 'created', 'competitionId': None, 'payload': {}, 'ts': 'now'})
            event = await communicator.receive_json_from(timeout=5)
            self.assertEqual(event.get('type'), 'resource:changed')
            self.assertEqual(event.get('resource'), 'users')
            self.assertIsNone(event.get('competitionId'))

            # 断线重放：global 作用域只补发系统级事件
            seq_a = await sync_to_async(emit_resource_changed)(
                None, 'users', 'updated', {'id': 1})
            self.assertIsNotNone(seq_a)
            await communicator.send_json_to(
                {'type': 'replay', 'scope': 'global', 'lastSeq': int(seq_a) - 1})
            replay = None
            for _ in range(4):  # 期间可能夹带 emit 自身的 resource:changed
                msg = await communicator.receive_json_from(timeout=5)
                if msg.get('type') == 'resource:replay':
                    replay = msg
                    break
            self.assertIsNotNone(replay)
            self.assertEqual(replay.get('scope'), 'global')
            self.assertIn(seq_a, [e.get('seq') for e in replay.get('events', [])])
            await communicator.disconnect()

        async_to_sync(run)()
