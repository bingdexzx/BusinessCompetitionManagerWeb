"""个人档案 API（§12：GET /api/me/awards、GET /api/me/medals/{id}）。"""

from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSystemSuperAdmin
from apps.global_.profiles.models import AwardRecord, MedalAsset


def _award_data(a: AwardRecord) -> dict:
    return {
        'id': a.id,
        'competitionId': a.competition_id,
        'competitionName': a.competition_name,
        'teamName': a.team_name,
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
    """个人档案：历史参赛记录与获奖信息（含电子奖牌）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AwardRecord.objects.filter(user=request.user).select_related('medal')
        return Response([_award_data(a) for a in qs])


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
    """奖牌资产管理（仅系统超管）。"""

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
