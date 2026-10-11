"""权限/主体解析（§15 权限与账号体系）：用户 ↔ 公司 的可操作关系。

- 参赛代表：本队公司（队伍映射出的公司，teams.companyId）；
- 管理员（主席团）：所辖公司（membership.managed_companies）；
- 比赛超管 / 系统超管：本比赛全部公司（§15.2 权限矩阵）。
"""

from apps.common.context import get_competition_id
from apps.global_.memberships.models import CompetitionMembership


def user_membership(user, competition_id=None):
    competition_id = competition_id or get_competition_id()
    if not (user and user.is_authenticated and competition_id):
        return None
    return (
        CompetitionMembership.objects
        .filter(user=user, competition_id=competition_id, is_active=True)
        .first()
    )


def user_company_ids(user, competition_id=None) -> set:
    """用户在当前比赛可操作（创建/确认/修改）的公司 ID 集合（'*' = 全部）。"""
    competition_id = competition_id or get_competition_id()
    if not (user and user.is_authenticated and competition_id):
        return set()
    if user.is_superuser:
        return {'*'}
    membership = user_membership(user, competition_id)
    if membership is None:
        return set()
    if membership.identity == CompetitionMembership.Identity.COMP_SUPER_ADMIN:
        return {'*'}
    if membership.identity == CompetitionMembership.Identity.ADMIN:
        return {int(c) for c in (membership.managed_companies or [])}
    # 参赛代表：本队公司
    from apps.global_.teams.models import Team
    team_ids = Team.objects.filter(
        competition_id=competition_id, members__user=user,
    ).values_list('company_id', flat=True)
    return {int(c) for c in team_ids if c}


def can_act_for_company(user, company_id, competition_id=None) -> bool:
    ids = user_company_ids(user, competition_id)
    return '*' in ids or int(company_id or 0) in ids


def can_manage_competition(user, competition_id=None) -> bool:
    """系统超管 / 本比赛超管（审核修改申请、审核补录、调整产业与指派，§15.2）。"""
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    membership = user_membership(user, competition_id)
    return bool(membership and membership.identity == CompetitionMembership.Identity.COMP_SUPER_ADMIN)


def company_actor_ids(company_id) -> set:
    """对某公司可表态的用户 ID 集（队长/队员 + 所辖管理员 + 比赛超管）。"""
    competition_id = get_competition_id()
    ids = set()
    if not company_id or not competition_id:
        return ids
    from apps.global_.teams.models import Team

    for team in Team.objects.filter(competition_id=competition_id, company_id=company_id):
        ids.update(team.members.values_list('user_id', flat=True))
    for m in CompetitionMembership.objects.filter(
        competition_id=competition_id, is_active=True,
    ):
        if m.identity == CompetitionMembership.Identity.COMP_SUPER_ADMIN:
            ids.add(m.user_id)
        elif m.identity == CompetitionMembership.Identity.ADMIN:
            if int(company_id) in {int(c) for c in (m.managed_companies or [])}:
                ids.add(m.user_id)
    return ids


def competition_super_admin_ids(competition_id=None) -> set:
    """本比赛超级管理员的用户 ID 集（含系统超管）。"""
    competition_id = competition_id or get_competition_id()
    ids = set()
    if competition_id:
        ids.update(CompetitionMembership.objects.filter(
            competition_id=competition_id, is_active=True,
            identity=CompetitionMembership.Identity.COMP_SUPER_ADMIN,
        ).values_list('user_id', flat=True))
    from django.contrib.auth import get_user_model
    ids.update(get_user_model().objects.filter(is_superuser=True, is_active=True)
               .values_list('id', flat=True))
    return ids
