"""比赛 API（§12：创建比赛（图片/名称/办赛学校/地点/人员安排）、meta、生命周期）。"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import (
    IsSystemSuperAdmin, IsSystemOrCompetitionSuperAdmin, get_membership,
)
from apps.global_.competitions import services
from apps.global_.competitions.models import Competition
from apps.global_.schools.models import School


def _competition_data(c: Competition) -> dict:
    return {
        'id': c.id,
        'name': c.name,
        'code': c.code,
        'coverImage': c.cover_image,
        'hostSchoolId': c.host_school_id,
        'hostSchoolName': c.host_school.name if c.host_school else None,
        'location': c.location,
        'staffingInfo': c.staffing_info,
        'status': c.status,
        'statusLabel': c.get_status_display(),
        'dbName': c.db_name,
        'createdBy': c.created_by_id,
        'createdAt': c.created_at.isoformat(),
    }


class CompetitionListCreateView(APIView):
    """GET 比赛列表（系统超管看全部，用户看有身份的比赛）；POST 创建比赛（系统超管）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.is_superuser:
            qs = Competition.objects.all()
        else:
            qs = Competition.objects.filter(memberships__user=request.user, memberships__is_active=True)
        return Response([_competition_data(c) for c in qs.distinct()[:200]])

    def post(self, request):
        if not request.user.is_superuser:
            return Response({'code': 403, 'message': '需要系统超级管理员权限', 'details': ''}, status=403)
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'code': 400, 'message': '比赛名称必填', 'details': ''}, status=400)
        host_school = None
        host_school_id = request.data.get('hostSchoolId')
        if host_school_id:
            host_school = get_object_or_404(School, pk=host_school_id)
        competition = services.create_competition(
            name=name,
            created_by=request.user,
            cover_image=request.data.get('coverImage', '') or '',
            host_school=host_school,
            location=request.data.get('location', '') or '',
            staffing_info=request.data.get('staffingInfo', '') or '',
            code=(request.data.get('code') or '').strip(),
        )
        return Response(_competition_data(competition), status=status.HTTP_201_CREATED)


class CompetitionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_visible(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if request.user.is_superuser or get_membership(request.user, cid):
            return competition
        return None

    def get(self, request, cid):
        competition = self._get_visible(request, cid)
        if competition is None:
            return Response({'code': 403, 'message': '无权查看该比赛', 'details': ''}, status=403)
        return Response(_competition_data(competition))


class CompetitionMetaView(APIView):
    """完善比赛信息（§2.2 阶段四）：系统超管 / 本比赛超管（§15.2）。"""

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def patch(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        for field, key in (
            ('cover_image', 'coverImage'), ('location', 'location'),
            ('staffing_info', 'staffingInfo'), ('name', 'name'),
        ):
            if key in request.data:
                setattr(competition, field, request.data.get(key) or '')
        if 'hostSchoolId' in request.data:
            school_id = request.data.get('hostSchoolId')
            competition.host_school = get_object_or_404(School, pk=school_id) if school_id else None
        competition.save()
        return Response(_competition_data(competition))


class CompetitionTransitionView(APIView):
    """生命周期转移（§10.1）：完善比赛信息+激活码 → 开赛 → 结束比赛 → 结算 → 关闭。"""

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def post(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        target = request.data.get('target') or ''
        try:
            competition.transition_to(target)
        except ValueError as exc:
            return Response({'code': 400, 'message': str(exc), 'details': ''}, status=400)
        return Response(_competition_data(competition))
