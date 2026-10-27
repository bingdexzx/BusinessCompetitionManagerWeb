"""WebSocket 实时通知（§5.1 Channels、§13 消息中心实时推送、§14.3 WebSocket 入网络日志）。

- 端点：``/ws/notifications?token=<access>``（JWT 鉴权，tokenVersion 校验）；
- 连接后加入 ``user_<id>`` 分组（个人通知）与 ``global`` 分组（系统级资源变更广播，
  用户/学校/比赛/插件等无比赛上下文的资源）；按比赛订阅 ``comp_<cid>`` 后再收该比赛的
  资源变更（``messages.services.send_message`` 落库后经 ``user_<id>`` 实时推送）；
- 连接/断开事件按 §14.3 写入网络日志（method=WS）。
"""

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.common.broadcast import GLOBAL_GROUP
from apps.common.devices import parse_user_agent


def _is_global_scope(content: dict, cid: int) -> bool:
    """是否为系统级（global）作用域：显式 ``scope=global``，或没有比赛 id。"""
    return str(content.get('scope') or '').strip().lower() == GLOBAL_GROUP or not cid


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """个人通知推送通道（合同确认提醒 / 修改审核 / 补录审核 / 结算完成等）。"""

    async def connect(self):
        self.user = await self._authenticate()
        if self.user is None:
            await self.close(code=4401)  # 未授权
            return
        self.group_name = f'user_{self.user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        # 系统级资源变更（全局库）：所有登录连接默认订阅，无需额外鉴权
        await self.channel_layer.group_add(GLOBAL_GROUP, self.channel_name)
        await self.accept()
        await database_sync_to_async(self._log_ws)('WS_CONNECT', 101)

    async def disconnect(self, code):
        if getattr(self, 'user', None) is not None:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self.channel_layer.group_discard(GLOBAL_GROUP, self.channel_name)
            await database_sync_to_async(self._log_ws)('WS_DISCONNECT', code or 1000)

    async def receive_json(self, content, **kwargs):
        # 前端可发 {"type": "ping"} 保活
        if isinstance(content, dict) and content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})
            return
        # 资源变更订阅（2026-10：实时广播 + 断线 seq 重放）
        # 两个作用域：scope=global（系统级资源，连接时已入组）/ competitionId=<cid>（比赛级）
        if isinstance(content, dict) and content.get('type') == 'subscribe':
            cid = int(content.get('competitionId') or 0)
            if _is_global_scope(content, cid):
                # 连接时已加入 global 分组，这里只回执（前端据此推进游标/记录订阅）
                await self.send_json(
                    {'type': 'resource:subscribed', 'scope': GLOBAL_GROUP, 'competitionId': None})
                return
            await self._subscribe(cid)
            return
        if isinstance(content, dict) and content.get('type') == 'unsubscribe':
            cid = int(content.get('competitionId') or 0)
            if cid:
                await self.channel_layer.group_discard(f'comp_{cid}', self.channel_name)
                await self.send_json({'type': 'resource:unsubscribed', 'competitionId': cid})
            return
        if isinstance(content, dict) and content.get('type') == 'replay':
            cid = int(content.get('competitionId') or 0)
            last_seq = int(content.get('lastSeq') or 0)
            from apps.common.broadcast import events_since
            if _is_global_scope(content, cid):
                events = await database_sync_to_async(events_since)(None, last_seq)
                await self.send_json(
                    {'type': 'resource:replay', 'scope': GLOBAL_GROUP,
                     'competitionId': None, 'events': events})
                return
            events = await database_sync_to_async(events_since)(cid, last_seq)
            await self.send_json(
                {'type': 'resource:replay', 'competitionId': cid, 'events': events})
            return

    async def _subscribe(self, competition_id: int):
        """订阅某比赛的资源变更广播（须对本比赛有读权限：成员/可操作公司/系统超管）。

        与 HTTP 读接口的成员门禁口径保持一致（membership 或 user_company_ids），
        否则「能读但订阅被拒」会造成页面读得到、实时刷不动的割裂。
        """
        if not competition_id:
            return

        def _allowed():
            from apps.common.authority import user_company_ids
            from apps.common.permissions import get_membership

            if self.user.is_superuser or get_membership(self.user, competition_id):
                return True
            return bool(user_company_ids(self.user, competition_id))

        if not await database_sync_to_async(_allowed)():
            await self.send_json({'type': 'resource:denied', 'competitionId': competition_id})
            return
        await self.channel_layer.group_add(f'comp_{competition_id}', self.channel_name)
        await self.send_json({'type': 'resource:subscribed', 'competitionId': competition_id})

    async def resource_changed(self, event):
        """group_send 资源变更信号入口（apps.common.broadcast.emit_resource_changed）。"""
        await self.send_json({
            'type': 'resource:changed',
            'seq': event.get('seq'),
            'resource': event.get('resource'),
            'action': event.get('action'),
            'competitionId': event.get('competitionId'),
            'payload': event.get('payload') or {},
            'ts': event.get('ts'),
        })

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
