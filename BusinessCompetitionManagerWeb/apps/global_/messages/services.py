"""站内信服务：发送（个人/公告/系统通知）+ WebSocket 实时推送。"""

from apps.global_.messages.models import Message, MessageRecipient


def _push(to_user_id, data: dict):
    """实时推送到 /ws/notifications（失败静默不影响业务）。"""
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
    except Exception:  # noqa: BLE001
        pass


def send_inmail(*, sender=None, title, body='', recipient_ids=(), kind=Message.Kind.PERSONAL,
                payload=None, competition_id=None) -> Message:
    """发送站内信（一信多收件人，自动去重；落库即推送）。"""
    ids = {int(u) for u in recipient_ids if u}
    if sender is not None:
        ids.discard(sender.id)  # 不给自己发
    if not ids:
        return None
    message = Message.objects.create(
        sender=sender,
        sender_name=(sender.username if sender else '系统'),
        kind=kind,
        title=title,
        body=body,
        payload=payload or {},
        competition_id=competition_id,
    )
    MessageRecipient.objects.bulk_create(
        [MessageRecipient(message=message, user_id=uid) for uid in ids])
    for uid in ids:
        _push(uid, {
            'type': 'notification',
            'id': message.id,
            'kind': message.kind,
            'title': title,
            'body': body,
            'payload': payload or {},
            'competitionId': competition_id,
            'createdAt': message.created_at.isoformat(),
        })
    return message


def send_system_notice(*, title, body='', recipient_ids=(), payload=None,
                       competition_id=None) -> Message:
    """系统自动通知（合同确认提醒/审核提醒等）：统一进收件箱，kind=SYSTEM。"""
    return send_inmail(
        sender=None, title=title, body=body, recipient_ids=recipient_ids,
        kind=Message.Kind.SYSTEM, payload=payload, competition_id=competition_id,
    )
