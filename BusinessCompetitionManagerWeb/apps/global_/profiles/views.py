"""个人档案 API（§12：GET /api/me/awards、GET /api/me/medals/{id}）。"""

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.profiles.models import AwardRecord, MedalAsset


_AWARD_KIND_LABELS = {'INDIVIDUAL': '个人奖', 'COLLECTIVE': '集体奖'}


def _award_data(a: AwardRecord) -> dict:
    return {
        'id': a.id,
        'competitionId': a.competition_id,
        'competitionName': a.competition_name,
        'teamName': a.team_name,
        # 人工发放的奖项（2026-10 需求变更）
        'awardName': a.award_name,
        'awardKind': a.award_kind,
        'awardKindLabel': _AWARD_KIND_LABELS.get(a.award_kind, ''),
        'rank': a.rank,
        'awardLevel': a.award_level,
        'score': a.score,
        'medalId': a.medal_id,
        'medalName': a.medal.display_name if a.medal else None,
        'detail': a.detail,
        'createdAt': a.created_at.isoformat(),
    }


def _medal_data(m: MedalAsset) -> dict:
    return {
        'id': m.id,
        'awardLevel': m.award_level,
        'displayName': m.display_name,
        'displayAsset': m.display_asset,
        'meta': m.meta,
    }


class MyAwardsView(APIView):
    """个人档案：参赛获奖记录（只含真正获得奖项的记录，含电子奖牌）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (AwardRecord.objects
              .filter(user=request.user)
              .exclude(award_name='')
              .select_related('medal'))
        return Response([_award_data(a) for a in qs])


def _holder_name(membership) -> str:
    """持有人：取账号当前的显示名，没设就用用户名（改名后票面跟着变）。"""
    user = membership.user
    return (user.display_name or '').strip() or user.username


def _ticket_data(membership) -> dict:
    """纪念券：优先用加入时定格的快照，旧数据按会员+比赛现拼一份。"""
    snapshot = membership.ticket_snapshot or {}
    holder = _holder_name(membership)
    if snapshot:
        return {
            'competitionId': snapshot.get('competitionId') or membership.competition_id,
            'competitionName': snapshot.get('competitionName')
            or membership.competition.name,
            'ticketNo': snapshot.get('ticketNo') or membership.ticket_no,
            'ticketImage': snapshot.get('ticketImage')
            or membership.competition.ticket_image,
            'identity': snapshot.get('identity') or membership.identity,
            'identityLabel': snapshot.get('identityLabel')
            or membership.get_identity_display(),
            'userName': holder,
            'joinedAt': snapshot.get('joinedAt') or membership.created_at.isoformat(),
        }
    return {
        'competitionId': membership.competition_id,
        'competitionName': membership.competition.name,
        'ticketNo': membership.ticket_no,
        'ticketImage': membership.competition.ticket_image,
        'identity': membership.identity,
        'identityLabel': membership.get_identity_display(),
        'userName': holder,
        'joinedAt': membership.created_at.isoformat(),
    }


class MyTicketsView(APIView):
    """个人档案：我的纪念票（加入比赛时定格的票面，含票号与票图）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from apps.global_.memberships.models import CompetitionMembership

        rows = (CompetitionMembership.objects
                .filter(user=request.user, is_active=True)
                .select_related('competition', 'user')
                .order_by('-created_at'))
        return Response([_ticket_data(row) for row in rows])


class MedalDetailView(APIView):
    """电子奖牌在线展示（仅在线展示，不提供下载，决策 D12）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, mid):
        medal = get_object_or_404(MedalAsset, pk=mid)
        return Response(_medal_data(medal))


class MedalListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([_medal_data(m) for m in MedalAsset.objects.all()])


class MedalManageView(APIView):
    """奖牌资产管理（仅系统超级管理员）。"""

    permission_classes = [IsSystemSuperAdmin]

    def post(self, request):
        medal, _ = MedalAsset.objects.update_or_create(
            award_level=request.data.get('awardLevel') or '',
            defaults={
                'display_name': request.data.get('displayName') or '',
                'display_asset': request.data.get('displayAsset') or '',
                'meta': request.data.get('meta') or {},
            },
        )
        return Response(_medal_data(medal), status=201)
