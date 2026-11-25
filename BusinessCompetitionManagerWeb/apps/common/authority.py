"""权限/主体解析（§15）：用户 ↔ 公司 的**可查看 / 可操作**关系。

2026-10 决策：公司由管理员分配给队伍后——**可查看**（``user_company_ids`` / ``can_view_company``）
队长与队员都能看本公司（合同、行情、公司表格等只读）；**可操作**（``user_operable_company_ids``
/ ``can_act_for_company``）只有队长能操作（下单/撤单、合同创建/确认/申请修改等），队员只读。
管理员（主席团）按所辖公司看/操作；比赛超级管理员身份已取消（2026-11），其权限并入**系统超级管理员**
（``is_superuser``）。
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
    """用户在当前比赛**可查看**的公司 ID 集合（'*' = 全部）。

    参赛代表取「本队公司」——**队长与队员都在内**（队员只读）；能否操作看 ``can_act_for_company``。
    管理员（主席团）**兼任队长/队员**时，本队公司与此人所辖公司取并集——否则"既当裁判又参赛"
    的人反而看不到自己队伍的公司。
    """
    competition_id = competition_id or get_competition_id()
    if not (user and user.is_authenticated and competition_id):
        return set()
    if user.is_superuser:
        return {'*'}
    membership = user_membership(user, competition_id)
    if membership is None:
        return set()
    from apps.global_.teams.models import Team
    team_ids = {int(c) for c in Team.objects.filter(
        competition_id=competition_id, members__user=user,
    ).values_list('company_id', flat=True) if c}
    if membership.identity == CompetitionMembership.Identity.ADMIN:
        return {int(c) for c in (membership.managed_companies or [])} | team_ids
    return team_ids


def user_operable_company_ids(user, competition_id=None) -> set:
    """用户在当前比赛**可操作**的公司 ID 集合（'*' = 全部）。

    2026-10 决策：公司分配给队伍后**只有队长**能操作本公司（下单/撤单、合同创建/确认/申请
    修改等），队员只读。管理员按所辖公司操作（兼任队长时并上本队公司），系统超级管理员全部可操作。
    """
    competition_id = competition_id or get_competition_id()
    if not (user and user.is_authenticated and competition_id):
        return set()
    if user.is_superuser:
        return {'*'}
    membership = user_membership(user, competition_id)
    if membership is None:
        return set()
    # 参赛代表：**仅队长**的本队公司
    from apps.global_.teams.models import Team
    captain_ids = {int(c) for c in Team.objects.filter(
        competition_id=competition_id, captain=user,
    ).values_list('company_id', flat=True) if c}
    if membership.identity == CompetitionMembership.Identity.ADMIN:
        return {int(c) for c in (membership.managed_companies or [])} | captain_ids
    return captain_ids


def can_read_competition(user, competition_id=None) -> bool:
    """能否读本比赛数据：本比赛成员（含只读队员）或系统超级管理员。

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
    """能否**查看**该公司（队长与队员都可以；受「查看公司信息」能力开关约束）。"""
    from apps.common.capabilities import has_capability

    if not has_capability(user, 'view.companies', competition_id):
        return False
    ids = user_company_ids(user, competition_id)
    return '*' in ids or int(company_id or 0) in ids


def can_act_for_company(user, company_id, competition_id=None) -> bool:
    """能否**操作**该公司（仅队长 / 所辖管理员 / 系统超级管理员；受「修改公司字段值」开关约束）。"""
    from apps.common.capabilities import has_capability

    if not has_capability(user, 'act.companies', competition_id):
        return False
    ids = user_operable_company_ids(user, competition_id)
    return '*' in ids or int(company_id or 0) in ids


def can_manage_competition(user, competition_id=None) -> bool:
    """比赛管理权限（审核修改申请、审核补录、调整产业与指派、数据管理写入等）。

    2026-11 决策：比赛超级管理员身份取消，权限并入**超级管理员**。
    """
    if user is None or not user.is_authenticated:
        return False
    return bool(user.is_superuser)


def audit_company_ids(user, competition_id=None) -> set:
    """审计信息（确认时间线 / 检查记录 / 效果审计 / 资金账本）的**可见公司范围**。

    ``'*'`` = 全部（系统超级管理员）；普通集合 = 仅这些公司（管理员按所辖公司）；
    **空集 = 完全没有审计可见性**（参赛代表，含队长与队员——不因参赛而看到任何审计流水）。
    """
    if user is None or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {'*'}
    membership = user_membership(user, competition_id)
    if membership is None:
        return set()
    if membership.identity == CompetitionMembership.Identity.ADMIN:
        return {int(c) for c in (membership.managed_companies or [])}
    return set()


def company_actor_ids(company_id) -> set:
    """对某公司可表态的用户 ID 集（队长/队员 + 所辖管理员 + 系统超级管理员）。"""
    competition_id = get_competition_id()
    ids = set()
    if not company_id or not competition_id:
        return ids
    from apps.global_.teams.models import Team

    for team in Team.objects.filter(competition_id=competition_id, company_id=company_id):
        ids.update(team.members.values_list('user_id', flat=True))
    ids.update(CompetitionMembership.objects.filter(
        competition_id=competition_id, is_active=True,
        identity=CompetitionMembership.Identity.ADMIN,
    ).values_list('user_id', flat=True))
    return ids


def company_strict_actor_ids(company_id) -> set:
    """对某公司可**表态/操作**的**严格**用户 ID 集（**仅队长** + 所辖管理员）。

    与 ``company_actor_ids`` 相比两处都收紧：排除比赛/系统超级管理员——超级权限不自动替公司投票
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
    """本比赛管理通知对象：系统超级管理员（比赛超级管理员身份已取消，2026-11）。"""
    ids = set()
    from django.contrib.auth import get_user_model
    ids.update(get_user_model().objects.filter(is_superuser=True, is_active=True)
               .values_list('id', flat=True))
    return ids
