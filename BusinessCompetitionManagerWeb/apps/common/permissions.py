"""通用权限（§15.2 权限矩阵）。"""

from rest_framework.permissions import BasePermission

from apps.common.context import get_competition_id
from apps.global_.memberships.models import CompetitionMembership


class IsSystemSuperAdmin(BasePermission):
    """超级管理员（§15.1：系统级只有超级管理员与用户）。"""

    message = '仅超级管理员可操作'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


def get_membership(user, competition_id=None):
    if not (user and user.is_authenticated):
        return None
    competition_id = competition_id or get_competition_id()
    if not competition_id:
        return None
    return (
        CompetitionMembership.objects
        .filter(user=user, competition_id=competition_id, is_active=True)
        .first()
    )


class IsSystemOrCompetitionSuperAdmin(BasePermission):
    """比赛超级管理员已取消：该权限等价于系统超级管理员。"""

    message = '仅超级管理员可操作'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)
