"""比赛成员身份服务：组队时自动补齐「参赛选手」身份。

需求（2026-10）：加入比赛后组队的队长/队员，都应以**参赛选手**身份出现在比赛成员里，
不能出现"队伍有人、成员列表没他"的状态。
"""

from apps.global_.memberships.models import CompetitionMembership


def ensure_player_membership(user, competition):
    """确保用户在本比赛有有效成员身份，返回 ``(membership, error, created)``。

    幂等且**不降级**：已是成员就复用（ADMIN / 比赛超管身份保持不动），
    没有成员身份则补一条 ``PLAYER``。已被管理员停用的身份不会被悄悄复活，
    而是返回错误让调用方明确拒绝。
    """
    membership = CompetitionMembership.objects.filter(
        user=user, competition=competition).first()
    if membership is None:
        membership = CompetitionMembership.objects.create(
            user=user, competition=competition,
            identity=CompetitionMembership.Identity.PLAYER,
            is_active=True,
        )
        return membership, None, True
    if not membership.is_active:
        return None, '你的参赛身份已被停用，请联系比赛管理员', False
    return membership, None, False


def ensure_and_announce(user, competition):
    """补齐身份；**新建**身份时广播 ``members``（让成员/用户管理页面实时刷新）。"""
    membership, error, created = ensure_player_membership(user, competition)
    if created:
        from apps.common.broadcast import emit_resource_changed

        emit_resource_changed(
            competition.id, 'members', 'created',
            {'userId': user.id, 'username': user.username, 'via': 'team'})
    return membership, error
