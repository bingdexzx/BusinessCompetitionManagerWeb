"""队伍与组队码 API（§12：组队 / 产业志愿 / 管理员调整）。

- ``POST .../teams``：队长建队（选产业 + 接受调剂的产业）；
- ``POST .../teams/join``：参赛代表凭**组队码**完成组队；
- ``PATCH .../teams/{id}/industry``：**比赛管理员手动调整**队伍产业（最终定夺），
  并在比赛库创建/更新公司（一队一公司）与产业字段初始值。
"""

import secrets
import string

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common import context as ctx
from apps.common.permissions import (
    IsSystemOrCompetitionSuperAdmin, get_membership,
)
from apps.global_.competitions.models import Competition
from apps.global_.memberships.models import CompetitionMembership
from apps.global_.teams.models import Team, TeamJoinCode, TeamMember


def _team_data(t: Team, company_name: str = '') -> dict:
    members = list(t.members.select_related('user').order_by('role', 'joined_at'))
    return {
        'id': t.id,
        'competitionId': t.competition_id,
        'name': t.name,
        'captainId': t.captain_id,
        'captainName': t.captain.username,
        'industryChoice': t.industry_choice,
        'industryAdjustAccepted': t.industry_adjust_accepted,
        'industryFinal': t.industry_final,
        'companyId': t.company_id,
        'companyName': company_name or '',
        'members': [
            {'userId': m.user_id, 'username': m.user.username,
             'displayName': m.user.display_name, 'role': m.role}
            for m in members
        ],
        'createdAt': t.created_at.isoformat(),
    }


def _company_name_map(competition, company_ids) -> dict:
    """读取比赛库中这些公司的名称（临时切换比赛上下文，用完**还原**）。

    组队列表要显示已分配的公司名，而公司表在比赛库；请求本身的上下文是比赛级的，
    这里切换后必须还原（清空会影响同一请求的后续处理）。
    """
    ids = [cid for cid in company_ids if cid]
    if not ids:
        return {}
    from apps.competition import provisioning
    from apps.competition.companies.models import Company

    prev_id, prev_alias = ctx.get_competition_id(), ctx.get_competition_alias()
    alias = provisioning.ensure_competition_db(competition.db_name)
    ctx.set_competition_context(competition.id, alias)
    try:
        return {c.id: c.name for c in Company.objects.filter(pk__in=ids)}
    finally:
        if prev_alias:
            ctx.set_competition_context(prev_id, prev_alias)
        else:
            ctx.clear_request_context()


def _industry_available(competition, industry_key: str) -> bool:
    """该产业是否已随比赛包导入（只有导入过的产业才能初始化公司字段值）。"""
    from apps.global_.packages.models import PackagePlugin

    return PackagePlugin.objects.filter(
        package__competition=competition, kind='INDUSTRY', key=industry_key).exists()


def _require_player(request, competition) -> CompetitionMembership:
    """加入组队的前提：本比赛的参赛身份（§2.2 阶段三）。"""
    m = get_membership(request.user, competition.id)
    if m is None and not request.user.is_superuser:
        return None
    return m


class TeamListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        if not (request.user.is_superuser or get_membership(request.user, cid)):
            return Response({'code': 403, 'message': '无权查看该比赛', 'details': ''}, status=403)
        teams = list(competition.teams.all().prefetch_related('members__user'))
        names = _company_name_map(competition, [t.company_id for t in teams])
        return Response([_team_data(t, names.get(t.company_id, '')) for t in teams])

    def post(self, request, cid):
        """队长建队：录入想要的产业与接受调剂的产业（§2.2 阶段三）。"""
        competition = get_object_or_404(Competition, pk=cid)
        membership = _require_player(request, competition)
        if membership is None:
            return Response({'code': 403, 'message': '需要本比赛参赛身份', 'details': ''}, status=403)
        if Team.objects.filter(competition=competition, members__user=request.user).exists():
            return Response({'code': 400, 'message': '你已加入其他队伍', 'details': ''}, status=400)
        name = (request.data.get('name') or '').strip()
        if not name:
            return Response({'code': 400, 'message': '队伍名称必填', 'details': ''}, status=400)

        team = Team.objects.create(
            competition=competition,
            name=name,
            captain=request.user,
            industry_choice=request.data.get('industryChoice') or [],
            industry_adjust_accepted=request.data.get('industryAdjustAccepted') or [],
        )
        TeamMember.objects.create(team=team, user=request.user, role=TeamMember.Role.CAPTAIN)
        return Response(_team_data(team), status=status.HTTP_201_CREATED)


class TeamDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid, tid):
        team = get_object_or_404(Team, pk=tid, competition_id=cid)
        return Response(_team_data(team))


class TeamJoinCodeView(APIView):
    """生成组队码（队长）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid, tid):
        team = get_object_or_404(Team, pk=tid, competition_id=cid)
        if team.captain_id != request.user.id and not request.user.is_superuser:
            return Response({'code': 403, 'message': '只有队长可以生成组队码', 'details': ''}, status=403)
        alphabet = string.ascii_uppercase + string.digits
        code = ''.join(secrets.choice(alphabet) for _ in range(8))
        join_code = TeamJoinCode.objects.create(
            team=team,
            code=code,
            expires_at=timezone.now() + timezone.timedelta(days=7),
            max_uses=int(request.data.get('maxUses') or 1),
            created_by=request.user.id,
        )
        return Response({
            'id': join_code.id, 'code': join_code.code,
            'expiresAt': join_code.expires_at.isoformat(),
            'maxUses': join_code.max_uses, 'usedCount': join_code.used_count,
        }, status=status.HTTP_201_CREATED)


class TeamJoinView(APIView):
    """参赛代表凭组队码完成组队（§2.2 阶段三入口二）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        competition = get_object_or_404(Competition, pk=cid)
        membership = _require_player(request, competition)
        if membership is None:
            return Response({'code': 403, 'message': '需要本比赛参赛身份', 'details': ''}, status=403)
        code = (request.data.get('code') or '').strip()
        join_code = TeamJoinCode.objects.select_related('team').filter(code=code).first()
        if join_code is None or join_code.team.competition_id != cid or not join_code.is_valid:
            return Response({'code': 400, 'message': '组队码无效或已过期', 'details': ''}, status=400)
        if Team.objects.filter(competition=competition, members__user=request.user).exists():
            return Response({'code': 400, 'message': '你已加入其他队伍', 'details': ''}, status=400)

        team = join_code.team
        TeamMember.objects.create(team=team, user=request.user, role=TeamMember.Role.MEMBER)
        join_code.used_count += 1
        join_code.save(update_fields=['used_count'])
        return Response(_team_data(team), status=status.HTTP_201_CREATED)


class TeamIndustryAdjustView(APIView):
    """比赛管理员手动调整队伍产业（§2.2 阶段三：最终产业分配由管理员定夺）。

    同时在比赛库创建/更新公司（一队一公司）并按产业插件回填初始字段值。
    """

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def patch(self, request, cid, tid):
        team = get_object_or_404(Team, pk=tid, competition_id=cid)
        industry_final = (request.data.get('industryFinal') or '').strip()
        team.industry_final = industry_final
        if 'industryChoice' in request.data:
            team.industry_choice = request.data.get('industryChoice') or []
        if 'industryAdjustAccepted' in request.data:
            team.industry_adjust_accepted = request.data.get('industryAdjustAccepted') or []
        team.save()

        if industry_final:
            _sync_team_company(team, request.user)
        return Response(_team_data(team))


class TeamCompanyAssignView(APIView):
    """分配/修改队伍公司（§2.2 阶段三；2026-10 决策）。

    管理员（系统超管 / 比赛超管）**选择产业 + 填写公司名称**为队伍分配公司：
    - 在比赛库创建/更新对应公司（一队一公司），按产业插件回填初始字段值；
    - 分配后**队长**获得该公司权限（可操作股票与合同），队员只读
      （见 apps.common.authority：user_company_ids 可查看 / user_operable_company_ids 仅队长）。
    """

    permission_classes = [IsSystemOrCompetitionSuperAdmin]

    def post(self, request, cid, tid):
        team = get_object_or_404(Team, pk=tid, competition_id=cid)
        industry_key = (request.data.get('industryKey')
                        or request.data.get('industryFinal') or '').strip()
        company_name = (request.data.get('companyName') or '').strip()

        if not industry_key:
            return Response({'code': 400, 'message': '请选择产业', 'details': ''}, status=400)
        if not company_name:
            return Response({'code': 400, 'message': '请填写公司名称', 'details': ''}, status=400)
        if len(company_name) > 120:
            return Response(
                {'code': 400, 'message': '公司名称最长 120 个字符', 'details': ''}, status=400)
        if not _industry_available(team.competition, industry_key):
            return Response({
                'code': 400,
                'message': f'产业「{industry_key}」尚未在本比赛导入（请先在比赛包中导入该产业插件）',
                'details': '',
            }, status=400)

        team.industry_final = industry_key
        team.save(update_fields=['industry_final', 'updated_at'])
        company = _sync_team_company(team, request.user, company_name=company_name)
        return Response(_team_data(team, company.name))


def _sync_team_company(team: Team, operator, company_name: str = ''):
    """队伍 → 公司（比赛库）：创建/更新公司并初始化产业字段值。

    ``company_name`` 为空时退回队伍名（兼容旧的「调整产业」入口）。
    """
    from apps.competition import provisioning
    from apps.competition.companies.models import Company
    from apps.competition.industries import services as industry_services

    competition = team.competition
    name = (company_name or '').strip() or team.name
    alias = provisioning.ensure_competition_db(competition.db_name)
    ctx.set_competition_context(competition.id, alias)
    try:
        if team.company_id:
            company = Company.objects.filter(pk=team.company_id).first()
        else:
            company = None
        if company is None:
            company = Company.objects.create(
                name=name, industry_key=team.industry_final, team_id=team.id,
            )
            initial = industry_services.industry_initial_values(competition, team.industry_final)
            industry_services.initialize_company_values(company, initial)
        else:
            old_key = company.industry_key
            company.name = name
            company.industry_key = team.industry_final
            company.team_id = team.id
            company.save()
            if old_key != team.industry_final:
                initial = industry_services.industry_initial_values(competition, team.industry_final)
                industry_services.initialize_company_values(company, initial)
        team.company_id = company.id
        team.save(update_fields=['company_id'])
    finally:
        ctx.clear_request_context()
    return company
