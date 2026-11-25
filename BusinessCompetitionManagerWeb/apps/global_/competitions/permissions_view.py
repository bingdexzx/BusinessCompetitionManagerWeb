"""角色权限矩阵 API（2026-11）：只配置「参赛代表 / 管理员」能看什么、能操作什么。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition
from apps.common.capabilities import (
    CAPABILITIES, CAPABILITY_KEYS, DEFAULT_MATRIX, ROLES, _sanitize, get_matrix,
)
from apps.global_.competitions.models import Competition


class CompetitionPermissionView(APIView):
    """GET/PUT /api/competitions/{cid}/permissions：读取与保存角色权限矩阵。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        competition = Competition.objects.using('default').filter(pk=cid).first()
        if competition is None:
            return Response({'code': 404, 'message': '比赛不存在', 'details': ''}, status=404)
        return Response({
            'roles': ROLES,
            'capabilities': CAPABILITIES,
            'matrix': get_matrix(competition),
            'defaults': DEFAULT_MATRIX,
        })

    def put(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '仅超级管理员可操作', 'details': ''},
                            status=403)
        competition = Competition.objects.using('default').filter(pk=cid).first()
        if competition is None:
            return Response({'code': 404, 'message': '比赛不存在', 'details': ''}, status=404)

        raw = request.data.get('matrix')
        if not isinstance(raw, dict):
            return Response({'code': 400, 'message': 'matrix 必须是对象', 'details': ''},
                            status=400)
        for role, keys in raw.items():
            if role not in [item['key'] for item in ROLES]:
                return Response({'code': 400, 'message': f'未知角色 {role}', 'details': ''},
                                status=400)
            if not isinstance(keys, list):
                return Response({'code': 400, 'message': f'{role} 的能力列表必须是数组',
                                 'details': ''}, status=400)
            unknown = [k for k in keys if k not in CAPABILITY_KEYS]
            if unknown:
                return Response({'code': 400, 'message': f'未知能力：{", ".join(unknown)}',
                                 'details': ''}, status=400)

        competition.permissions = _sanitize(raw)
        competition.save(update_fields=['permissions', 'updated_at'])
        return Response({
            'roles': ROLES, 'capabilities': CAPABILITIES,
            'matrix': get_matrix(competition), 'defaults': DEFAULT_MATRIX,
        })
