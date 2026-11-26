"""比赛 API（§12：创建比赛（图片/名称/办赛学校/地点/人员安排）、meta、生命周期）。"""

from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, IntegerField, Value, When
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import (
    IsSystemOrCompetitionSuperAdmin, get_membership,
)
from apps.global_.competitions import services
from apps.global_.competitions.models import Competition
from apps.global_.schools.models import School


def _school_ids_from(data) -> list:
    """办赛学校 ID 列表：优先 hostSchoolIds（数组），兼容旧的单值 hostSchoolId。"""
    raw = data.get('hostSchoolIds')
    if raw is None:
        raw = data.get('hostSchoolId')
        if raw in (None, ''):
            return []
        raw = [raw]
    ids = []
    for item in raw or []:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _competition_data(c: Competition) -> dict:
    schools = list(c.host_schools.all())
    return {
        'id': c.id,
        'name': c.name,
        'code': c.code,
        'coverImage': c.cover_image,
        'ticketImage': c.ticket_image,
        'hostSchoolIds': [s.id for s in schools],
        'hostSchoolNames': [s.name for s in schools],
        # 兼容旧字段（单校）
        'hostSchoolId': schools[0].id if schools else None,
        'hostSchoolName': schools[0].name if schools else None,
        'location': c.location,
        'staffingInfo': c.staffing_info,
        'status': c.status,
        'statusLabel': c.get_status_display(),
        'dbName': c.db_name,
        'createdBy': c.created_by_id,
        'createdAt': c.created_at.isoformat(),
    }


class CompetitionListCreateView(APIView):
    """GET 比赛列表（系统超级管理员看全部，用户看有身份的比赛）；POST 创建比赛（系统超级管理员）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cache_key = f'competitions:list:v1:{request.user.pk}'
        if not settings.TESTING:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)
        if request.user.is_superuser:
            qs = Competition.objects.all()
        else:
            qs = Competition.objects.filter(memberships__user=request.user, memberships__is_active=True)
        # 已结束（CLOSED）的比赛自动排到最后；其余按创建时间倒序（新比赛在前）
        qs = qs.annotate(
            _ended_last=Case(
                When(status=Competition.Status.CLOSED, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        ).order_by('_ended_last', '-created_at')
        data = [_competition_data(c) for c in qs.distinct()[:200]]
        if not settings.TESTING:
            cache.set(cache_key, data, 10)
        return Response(data)

    def post(self, request):
        if not request.user.is_superuser:
            return Response({'code': 403, 'message': '仅超级管理员可操作', 'details': ''}, status=403)
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'code': 400, 'message': '比赛名称必填', 'details': ''}, status=400)
        school_ids = _school_ids_from(request.data)
        if not school_ids:
            return Response({'code': 400, 'message': '请选择办赛学校', 'details': ''}, status=400)
        schools = list(School.objects.filter(pk__in=school_ids))
        if len(schools) != len(set(school_ids)):
            return Response({'code': 400, 'message': '办赛学校不存在', 'details': ''}, status=400)
        code = (request.data.get('code') or '').strip()
        if code and Competition.objects.filter(code=code).exists():
            return Response({'code': 400, 'message': '比赛代码已存在', 'details': ''}, status=400)
        try:
            competition = services.create_competition(
                name=name,
                created_by=request.user,
                cover_image=request.data.get('coverImage', '') or '',
                ticket_image=request.data.get('ticketImage', '') or '',
                host_schools=schools,
                location=request.data.get('location', '') or '',
                staffing_info=request.data.get('staffingInfo', '') or '',
                code=code,
            )
        except IntegrityError:
            # 自动生成的比赛代码撞车（如删除后序号复用）：重试一次新代码
            return Response(
                {'code': 400, 'message': '比赛代码已存在，请指定一个比赛代码后重试', 'details': ''},
                status=400,
            )
        cache.delete(f'competitions:list:v1:{request.user.pk}')
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
    """完善比赛信息（§2.2 阶段四）：系统超级管理员 / 本比赛超级管理员（§15.2）。"""

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def patch(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if 'name' in request.data:
            name = (request.data.get('name') or '').strip()
            if not name:
                return Response({'code': 400, 'message': '比赛名称必填', 'details': ''}, status=400)
            competition.name = name
        if 'code' in request.data:
            code = (request.data.get('code') or '').strip()
            if not code:
                return Response({'code': 400, 'message': '比赛代码不能为空', 'details': ''}, status=400)
            if len(code) > 32:
                return Response({'code': 400, 'message': '比赛代码最长 32 个字符', 'details': ''}, status=400)
            if Competition.objects.exclude(pk=competition.pk).filter(code=code).exists():
                return Response({'code': 400, 'message': '比赛代码已存在', 'details': ''}, status=400)
            competition.code = code
        for field, key in (('cover_image', 'coverImage'),
                           ('ticket_image', 'ticketImage'),
                           ('location', 'location'),
                           ('staffing_info', 'staffingInfo')):
            if key in request.data:
                setattr(competition, field, request.data.get(key) or '')
        if 'hostSchoolIds' in request.data or 'hostSchoolId' in request.data:
            school_ids = _school_ids_from(request.data)
            if not school_ids:
                return Response({'code': 400, 'message': '请选择办赛学校', 'details': ''}, status=400)
            schools = list(School.objects.filter(pk__in=school_ids))
            if len(schools) != len(set(school_ids)):
                return Response({'code': 400, 'message': '办赛学校不存在', 'details': ''}, status=400)
            competition.host_schools.set(schools)
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


class DashboardLayoutView(APIView):
    """仪表盘布局（比赛包 dashboard.json，2026-10 决策）。

    组件只声明样式与**产业字段绑定**（bind.table/fieldKey/aggregate）：
    - `components`：通用区（「全部」页签，聚合全部可操作公司）；
    - `industries.<产业key>`：该产业专属分区（只聚合该产业公司，字段键即该产业插件字段）。
    字段值由前端用 /companies + /companies/{id}/tables 聚合渲染（只看自己可操作的公司：
    本队公司或被分配管理的公司）。可见性 = 本比赛成员。
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if not (request.user.is_superuser or get_membership(request.user, cid)):
            return Response({'code': 403, 'message': '你不是本比赛成员', 'details': ''}, status=403)
        layout = competition.dashboard_layout or {}
        return Response({
            'title': layout.get('title') or '仪表盘',
            'components': layout.get('components') or [],
            # 按产业分屏：industries.<产业key> = {title?, components}
            'industries': layout.get('industries') or {},
            'updatedAt': competition.updated_at.isoformat(),
        })
