"""比赛内消息服务（§6.2 messages、§13 消息中心；WebSocket 实时推送见 §5.1）。"""

from apps.competition.messages.models import Message


def send_message(to_user_id, *, kind='', title='', body='', payload=None) -> Message:
    if not to_user_id:
        return None
    message = Message.objects.create(
        to_user_id=to_user_id, kind=kind, title=title, body=body,
        payload=payload or {},
    )
    _push(to_user_id, {
        'type': 'notification',
        'id': message.id,
        'kind': kind,
        'title': title,
        'body': body,
        'payload': payload or {},
        'createdAt': message.created_at.isoformat(),
    })
    return message


def _push(to_user_id, data: dict):
    """实时推送到 /ws/notifications（InMemory/Redis 通道层任一；失败静默不影响业务）。"""
    try:
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f'user_{to_user_id}',
            {'type': 'user.notification', 'payload': data},
        )
    except Exception:  # noqa: BLE001 —— 推送绝不影响消息落库
        pass


def notify_competition_super_admins(*, kind='', title='', body='', payload=None):
    from apps.common.authority import competition_super_admin_ids
    for uid in competition_super_admin_ids():
        send_message(uid, kind=kind, title=title, body=body, payload=payload)
