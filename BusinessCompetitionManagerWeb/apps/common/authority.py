"""权限/主体解析（§15）：用户 ↔ 公司 的**可查看 / 可操作**关系。

2026-10 决策：公司由管理员分配给队伍后——**可查看**（``user_company_ids`` / ``can_view_company``）
队长与队员都能看本公司（合同、行情、公司表格等只读）；**可操作**（``user_operable_company_ids``
/ ``can_act_for_company``）只有队长能操作（下单/撤单、合同创建/确认/申请修改等），队员只读。
其余口径：管理员看/操作所辖公司，比赛超管/系统超管看/操作本比赛全部公司（§15.2 权限矩阵）。"""

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
    """用户在当前比赛**可查看**的公司 ID 集合（'*' = 全部）。

    参赛代表取「本队公司」——**队长与队员都在内**（队员只读）；能否操作看 ``can_act_for_company``。"""
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
    from apps.global_.teams.models import Team
    team_ids = Team.objects.filter(
        competition_id=competition_id, members__user=user,
    ).values_list('company_id', flat=True)
    return {int(c) for c in team_ids if c}


def user_operable_company_ids(user, competition_id=None) -> set:
    """用户在当前比赛**可操作**的公司 ID 集合（'*' = 全部）。

    2026-10 决策：公司分配给队伍后**只有队长**能操作本公司（下单/撤单、合同创建/确认/申请
    修改等），队员只读。管理员按所辖公司操作，超管全部可操作。
    """
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
    # 参赛代表：**仅队长**的本队公司
    from apps.global_.teams.models import Team
    captain_ids = Team.objects.filter(
        competition_id=competition_id, captain=user,
    ).values_list('company_id', flat=True)
    return {int(c) for c in captain_ids if c}


def can_read_competition(user, competition_id=None) -> bool:
    """能否读本比赛数据：本比赛成员（含只读队员）或系统超管。

    basedata / fiscal / regions / stock 原先各自复制了同一段判断，收敛到此处避免口径漂移。"""
    if user is None or not user.is_authenticated:
        return False
    competition_id = competition_id or get_competition_id()
    if not competition_id:
        return False
    if user.is_superuser:
        return True
    if user_membership(user, competition_id) is not None:
        return True
    return bool(user_company_ids(user, competition_id))


def can_view_company(user, company_id, competition_id=None) -> bool:
    """能否**查看**该公司（队长与队员都可以）。"""
    ids = user_company_ids(user, competition_id)
    return '*' in ids or int(company_id or 0) in ids


def can_act_for_company(user, company_id, competition_id=None) -> bool:
    """能否**操作**该公司（仅队长 / 所辖管理员 / 超管）。"""
    ids = user_operable_company_ids(user, competition_id)
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


def company_strict_actor_ids(company_id) -> set:
    """对某公司可**表态/操作**的**严格**用户 ID 集（**仅队长** + 所辖管理员）。

    与 ``company_actor_ids`` 相比两处都收紧：排除比赛/系统超管——超级权限不自动替公司投票
    （逐方确认按公司计票，§3.3 T8）；只取队长——队员只读，不能代公司表态（2026-10 决策）。
    """
    competition_id = get_competition_id()
    ids = set()
    if not company_id or not competition_id:
        return ids
    from apps.global_.teams.models import Team

    ids.update(
        Team.objects.filter(competition_id=competition_id, company_id=company_id)
        .values_list('captain_id', flat=True)
    )
    for m in CompetitionMembership.objects.filter(
        competition_id=competition_id, is_active=True,
        identity=CompetitionMembership.Identity.ADMIN,
    ):
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
