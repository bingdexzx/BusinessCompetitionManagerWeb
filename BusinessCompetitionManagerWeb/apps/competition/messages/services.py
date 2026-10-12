"""比赛内通知服务（兼容入口）——统一写入**全局站内信收件箱**（kind=SYSTEM）。

历史：早期通知落在比赛库 messages 表；按需求方口径，消息中心独立于比赛、属系统级站内信，
系统自动通知（合同确认/修改/补录审核等）与站内信进同一收件箱（带「系统通知」标记与来源链接）。
"""

from apps.common.authority import competition_super_admin_ids
from apps.common.context import get_competition_id
from apps.global_.messages.services import send_system_notice


def send_message(to_user_id, *, kind='', title='', body='', payload=None):
    """系统通知（单收件人）：统一进全局站内信收件箱 + WebSocket 实时推送。"""
    if not to_user_id:
        return None
    return send_system_notice(
        title=title,
        body=(f'[{kind}] ' if kind else '') + body,
        recipient_ids=[to_user_id],
        payload={**(payload or {}), 'noticeKind': kind},
        competition_id=get_competition_id(),
    )


def notify_competition_super_admins(*, kind='', title='', body='', payload=None):
    for uid in competition_super_admin_ids():
        send_message(uid, kind=kind, title=title, body=body, payload=payload)
