"""比赛内审计 API（§12：GET .../audit-logs）。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition
from apps.competition.audit.models import AuditLog


class AuditLogListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '仅超级管理员可操作', 'details': ''}, status=403)
        qs = AuditLog.objects.all()
        params = request.query_params
        if params.get('actorId'):
            qs = qs.filter(actor_id=params['actorId'])
        if params.get('actor'):
            actor = params['actor'].strip()
            if actor.isdigit():
                qs = qs.filter(actor_id=int(actor))
            elif actor:
                qs = qs.filter(actor_username__icontains=actor)
        if params.get('action'):
            qs = qs.filter(action=params['action'])
        if params.get('target'):
            qs = qs.filter(target__icontains=params['target'])
        if params.get('from'):
            qs = qs.filter(occurred_at__gte=params['from'])
        if params.get('to'):
            qs = qs.filter(occurred_at__lte=params['to'])
        limit = min(int(params.get('limit', 50) or 50), 200)
        return Response([
            {
                'id': r.id, 'action': r.action, 'actorId': r.actor_id,
                'actorUsername': r.actor_username, 'target': r.target,
                'payload': r.payload, 'traceId': r.trace_id,
                'occurredAt': r.occurred_at.isoformat(),
            }
            for r in qs[:limit]
        ])
