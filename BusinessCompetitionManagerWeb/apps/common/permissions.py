"""通用权限（§15.2 权限矩阵）。"""

from rest_framework.permissions import BasePermission

from apps.common.context import get_competition_id
from apps.global_.memberships.models import CompetitionMembership


class IsSystemSuperAdmin(BasePermission):
    """系统超级管理员（§15.1：系统级只有超管与用户）。"""

    message = '需要系统超级管理员权限'

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


def is_competition_super_admin(user, competition_id=None):
    m = get_membership(user, competition_id)
    return bool(m and m.identity == CompetitionMembership.Identity.COMP_SUPER_ADMIN)


class IsSystemOrCompetitionSuperAdmin(BasePermission):
    message = '需要系统超管或本比赛超管权限'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated
            and (user.is_superuser or is_competition_super_admin(user))
        )
