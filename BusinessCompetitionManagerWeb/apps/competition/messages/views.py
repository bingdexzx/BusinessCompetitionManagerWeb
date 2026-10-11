"""比赛内消息 API（§13 消息中心、§6.2 messages）。"""

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.competition.messages.models import Message


def _message_data(m: Message) -> dict:
    return {
        'id': m.id, 'kind': m.kind, 'title': m.title, 'body': m.body,
        'payload': m.payload, 'readAt': m.read_at.isoformat() if m.read_at else None,
        'createdAt': m.created_at.isoformat(),
    }


class MessageListView(APIView):
    """当前用户在本比赛的消息（未读在前）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        qs = Message.objects.filter(to_user_id=request.user.id)
        if request.query_params.get('unread') == '1':
            qs = qs.filter(read_at__isnull=True)
        return Response([_message_data(m) for m in qs[:200]])


class MessageReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cid, pk):
        message = Message.objects.filter(pk=pk, to_user_id=request.user.id).first()
        if message and message.read_at is None:
            message.read_at = timezone.now()
            message.save(update_fields=['read_at'])
        return Response({'ok': True})


class MyMessagesView(APIView):
    """跨比赛消息汇总（个人档案 / 消息中心）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.competition import provisioning
        from apps.common import context as ctx
        from apps.global_.memberships.models import CompetitionMembership

        out = []
        memberships = CompetitionMembership.objects.filter(
            user=request.user, is_active=True).select_related('competition')
        for m in memberships:
            if not m.competition.db_name:
                continue
            alias = provisioning.ensure_competition_db(m.competition.db_name)
            ctx.set_competition_context(m.competition_id, alias)
            try:
                for msg in Message.objects.filter(to_user_id=request.user.id)[:100]:
                    data = _message_data(msg)
                    data['competitionId'] = m.competition_id
                    data['competitionName'] = m.competition.name
                    out.append(data)
            finally:
                ctx.clear_request_context()
        out.sort(key=lambda d: d['createdAt'], reverse=True)
        return Response(out[:200])
