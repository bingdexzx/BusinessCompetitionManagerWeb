"""WebSocket 实时通知（§5.1 Channels、§13 消息中心实时推送、§14.3 WebSocket 入网络日志）。

- 端点：``/ws/notifications?token=<access>``（JWT 鉴权，tokenVersion 校验）；
- 连接后加入 ``user_<id>`` 分组；``messages.services.send_message`` 落库后实时推送；
- 连接/断开事件按 §14.3 写入网络日志（method=WS）。
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.common.devices import parse_user_agent


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """个人通知推送通道（合同确认提醒 / 修改审核 / 补录审核 / 结算完成等）。"""

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close(code=4401)  # 未授权
            return
        self.group_name = f'user_{self.user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await database_sync_to_async(self._log_ws)('WS_CONNECT', 101)

    async def disconnect(self, code):
        if getattr(self, 'user', None) is not None:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await database_sync_to_async(self._log_ws)('WS_DISCONNECT', code or 1000)

    async def receive_json(self, content, **kwargs):
        # 前端可发 {"type": "ping"} 保活
        if isinstance(content, dict) and content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def user_notification(self, event):
        """group_send 消息入口（messages.services._push 使用同一 type）。"""
        await self.send_json(event.get('payload') or {})

    # ------------------------------------------------------------ 鉴权

    async def _authenticate(self):
        from urllib.parse import parse_qs

        from asgiref.sync import sync_to_async
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        query = parse_qs(self.scope.get('query_string', b'').decode())
        raw = (query.get('token') or [''])[0]
        if not raw:
            return None

        def _load_user():
            from django.contrib.auth import get_user_model
            try:
                validated = AccessToken(raw)
                user_id = validated.get('user_id') or validated.get('uid')
                user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
                if user is None:
                    return None
                token_version = validated.get('tv')
                if token_version is not None and int(token_version) != user.token_version:
                    return None
                return user
            except (InvalidToken, TokenError, ValueError):
                return None

        return await sync_to_async(_load_user)()

    # ------------------------------------------------------------ 网络日志（§14.3）

    def _log_ws(self, event: str, status: int):
        from apps.global_.logs.models import NetworkLog

        headers = {k.decode(): v.decode() for k, v in self.scope.get('headers', [])}
        ua = headers.get('user-agent', '')
        parsed = parse_user_agent(ua)
        snapshot = {
            'ua': ua[:500],
            'os': parsed['os'],
            'browser': parsed['browser'],
            'screen': headers.get('x-device-screen', ''),
            'ip': self._client_ip(),
        }
        try:
            NetworkLog.objects.create(
                trace_id=headers.get('x-trace-id', '') or '',
                user=getattr(self, 'user', None),
                device_snapshot=snapshot,
                method='WS',
                path=f'/ws/notifications [{event}]',
                status=status,
                ip=snapshot['ip'] or None,
            )
        except Exception:  # noqa: BLE001 —— 日志绝不影响通道
            pass

    def _client_ip(self) -> str:
        client = self.scope.get('client') or ('', 0)
        return client[0] or ''
