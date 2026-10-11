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
            return Response({'code': 403, 'message': '需要超级管理员权限', 'details': ''}, status=403)
        qs = AuditLog.objects.all()
        if request.query_params.get('actorId'):
            qs = qs.filter(actor_id=request.query_params['actorId'])
        if request.query_params.get('action'):
            qs = qs.filter(action__icontains=request.query_params['action'])
        limit = min(int(request.query_params.get('limit', 50) or 50), 200)
        return Response([
            {
                'id': r.id, 'action': r.action, 'actorId': r.actor_id,
                'actorUsername': r.actor_username, 'target': r.target,
                'payload': r.payload, 'traceId': r.trace_id,
                'occurredAt': r.occurred_at.isoformat(),
            }
            for r in qs[:limit]
        ])
