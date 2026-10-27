"""站内信 API（系统级，独立于比赛）。

- 收件箱 / 发件箱 / 已读 / 全部已读；
- 发送（`POST /api/messages`）：**个人自由**，**按比赛批量（公告）仅超管**（需求方口径）；
- 通讯录（`GET /api/messages/address-book`）：收件人多选框数据（比赛 + 个人）。
"""

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.messages.models import Message, MessageRecipient
from apps.global_.messages.services import send_inmail

User = get_user_model()


def _message_data(m: Message) -> dict:
    return {
        'id': m.id,
        'kind': m.kind,
        'kindLabel': m.get_kind_display(),
        'title': m.title,
        'body': m.body,
        'payload': m.payload or {},
        'competitionId': m.competition_id,
        'senderId': m.sender_id,
        'senderName': m.sender_name or (m.sender.username if m.sender else '系统'),
        'readAt': None,
        'createdAt': m.created_at.isoformat(),
    }


def _inbox_item(recipient: MessageRecipient) -> dict:
    m = recipient.message
    data = _message_data(m)
    data['recipientId'] = recipient.id  # 已读操作按收件人记录定位
    data['readAt'] = recipient.read_at.isoformat() if recipient.read_at else None
    return data


class InboxView(APIView):
    """我的收件箱（站内信/公告/系统通知统一收件箱）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = MessageRecipient.objects.filter(user=request.user).select_related('message', 'message__sender')
        if request.query_params.get('unread') == '1':
            qs = qs.filter(read_at__isnull=True)
        kind = request.query_params.get('kind')
        if kind:
            qs = qs.filter(message__kind=kind.upper())
        limit = min(int(request.query_params.get('limit', 50) or 50), 200)
        offset = int(request.query_params.get('offset', 0) or 0)
        total = qs.count()
        rows = qs.order_by('-message__created_at')[offset:offset + limit]
        return Response({
            'total': total,
            'unread': MessageRecipient.objects.filter(user=request.user, read_at__isnull=True).count(),
            'items': [_inbox_item(r) for r in rows],
        })


class SentView(APIView):
    """我发送的站内信。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Message.objects.filter(sender=request.user).prefetch_related('recipients')
        rows = qs.order_by('-created_at')[:100]
        out = []
        for m in rows:
            data = _message_data(m)
            data['recipients'] = [
                {'userId': r.user_id, 'username': r.user.username,
                 'readAt': r.read_at.isoformat() if r.read_at else None}
                for r in m.recipients.select_related('user')
            ]
            out.append(data)
        return Response(out)


class SendView(APIView):
    """发送站内信（需求方口径：个人自由；按比赛批量公告仅超管）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        title = (request.data.get('title') or '').strip()
        body = request.data.get('body') or ''
        if not title:
            return Response({'code': 400, 'message': '标题必填', 'details': ''}, status=400)

        user_ids = {int(u) for u in (request.data.get('recipientUserIds') or []) if str(u).isdigit()}
        competition_ids = {int(c) for c in (request.data.get('competitionIds') or []) if str(c).isdigit()}

        # 按比赛批量 = 公告：仅超管（系统超管或所选比赛的比赛超管，逐个校验）
        if competition_ids:
            if not request.user.is_superuser:
                for cid in competition_ids:
                    if not can_manage_competition(request.user, cid):
                        return Response(
                            {'code': 403,
                             'message': '按比赛批量发送（公告）仅超级管理员可用（比赛 ' + str(cid) + ' 无权限）',
                             'details': ''},
                            status=403)
            for cid in competition_ids:
                user_ids.update(
                    CompetitionMembership.objects.filter(
                        competition_id=cid, is_active=True,
                    ).values_list('user_id', flat=True))

        if not user_ids:
            return Response({'code': 400, 'message': '请选择接收人', 'details': ''}, status=400)

        # 消息图片（2026-10 缺口补齐）：≤9 张，只接受本服务上传的图片 URL
        images = [str(u) for u in (request.data.get('images') or []) if isinstance(u, str)]
        if len(images) > 9:
            return Response({'code': 400, 'message': '图片最多 9 张', 'details': ''}, status=400)
        for url in images:
            if not url.startswith('/api/files/view/messages/') or len(url) > 2048:
                return Response(
                    {'code': 400, 'message': '图片地址非法（请先用图片上传接口上传）', 'details': ''},
                    status=400)

        kind = Message.Kind.ANNOUNCE if competition_ids else Message.Kind.PERSONAL
        message = send_inmail(
            sender=request.user, title=title, body=body,
            recipient_ids=user_ids, kind=kind,
            payload={'images': images} if images else None,
            competition_id=sorted(competition_ids)[0] if competition_ids else None,
        )
        if message is None:
            return Response({'code': 400, 'message': '接收人无效（不能只发给自己）', 'details': ''}, status=400)
        return Response(_message_data(message), status=status.HTTP_201_CREATED)


class ReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        recipient = MessageRecipient.objects.filter(pk=pk, user=request.user).first()
        if recipient and recipient.read_at is None:
            recipient.read_at = timezone.now()
            recipient.save(update_fields=['read_at'])
        return Response({'ok': True})


class ReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        count = MessageRecipient.objects.filter(
            user=request.user, read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({'ok': True, 'updated': count})


class AddressBookView(APIView):
    """收件人多选框数据：比赛（选中=全员）+ 个人（自动去重）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_superuser:
            from apps.global_.competitions.models import Competition
            competitions = [
                {'id': c.id, 'name': c.name,
                 'memberCount': CompetitionMembership.objects.filter(
                     competition=c, is_active=True).count()}
                for c in Competition.objects.all().order_by('-created_at')[:200]
            ]
            users = [
                {'id': u.id, 'username': u.username, 'displayName': u.display_name}
                for u in User.objects.filter(is_active=True).order_by('username')[:500]
            ]
        else:
            my_comp_ids = list(CompetitionMembership.objects.filter(
                user=request.user, is_active=True).values_list('competition_id', flat=True))
            from apps.global_.competitions.models import Competition
            competitions = [
                {'id': c.id, 'name': c.name,
                 'memberCount': CompetitionMembership.objects.filter(
                     competition=c, is_active=True).count()}
                for c in Competition.objects.filter(pk__in=my_comp_ids).order_by('-created_at')
            ]
            # 可选个人：与我同比赛的成员（含我自己）
            user_ids = set(CompetitionMembership.objects.filter(
                competition_id__in=my_comp_ids, is_active=True,
            ).values_list('user_id', flat=True))
            user_ids.add(request.user.id)
            users = [
                {'id': u.id, 'username': u.username, 'displayName': u.display_name}
                for u in User.objects.filter(pk__in=user_ids, is_active=True).order_by('username')
            ]
        return Response({'competitions': competitions, 'users': users})
