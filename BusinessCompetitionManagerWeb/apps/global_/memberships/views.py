"""比赛内身份 API（§12：GET .../members、POST .../members/assign）。

- 指派管理员（主席团）并设置所辖公司（§2.2 阶段三，由**超级管理员**操作）；
- 2026-11 决策：取消「比赛超级管理员」身份，其权限并入系统超级管理员。
"""

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership


def _member_data(m: CompetitionMembership) -> dict:
    return {
        'id': m.id,
        'userId': m.user_id,
        'username': m.user.username,
        'displayName': m.user.display_name,
        'identity': m.identity,
        'identityLabel': m.get_identity_display(),
        'managedCompanies': m.managed_companies,
        'isActive': m.is_active,
    }


class MemberListCreateView(APIView):
    """GET 列出比赛成员；POST 指派/调整身份与所辖公司（仅系统超级管理员）。"""

    permission_classes = [IsSystemSuperAdmin]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        members = (
            CompetitionMembership.objects
            .filter(competition=competition, is_active=True)
            .select_related('user')
            .order_by('identity', 'user__username')
        )
        return Response([_member_data(m) for m in members])

    def post(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        username = (request.data.get('username') or '').strip()
        identity = request.data.get('identity') or ''
        managed = request.data.get('managedCompanies') or []

        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            return Response({'code': 404, 'message': '用户不存在', 'details': ''}, status=404)
        if identity not in CompetitionMembership.Identity.values:
            return Response({'code': 400, 'message': '非法身份类型', 'details': ''}, status=400)

        membership, _ = CompetitionMembership.objects.update_or_create(
            user=user, competition=competition,
            defaults={'identity': identity, 'managed_companies': managed, 'is_active': True},
        )
        return Response(_member_data(membership), status=status.HTTP_201_CREATED)


class MemberDetailView(APIView):
    """调整所辖公司 / 停用身份（仅系统超级管理员）。"""

    permission_classes = [IsSystemSuperAdmin]

    def patch(self, request, cid, mid):
        competition = get_object_or_404(Competition, pk=cid)
        membership = get_object_or_404(
            CompetitionMembership, pk=mid, competition=competition,
        )
        if 'identity' in request.data:
            identity = request.data.get('identity') or ''
            if identity not in CompetitionMembership.Identity.values:
                return Response({'code': 400, 'message': '非法身份类型', 'details': ''}, status=400)
            membership.identity = identity
        if 'managedCompanies' in request.data:
            membership.managed_companies = request.data.get('managedCompanies') or []
        if 'isActive' in request.data:
            membership.is_active = bool(request.data.get('isActive'))
        membership.save()
        return Response(_member_data(membership))
