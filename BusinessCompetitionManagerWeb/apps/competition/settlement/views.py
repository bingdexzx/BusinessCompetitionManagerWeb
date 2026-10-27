"""结算与获奖 API（§12；2026-10 需求变更）。

- **结算只算分**：``POST .../settlement/run`` → 各公司得分 + 名次；
- **奖项人工设定**：``GET/POST .../settlement/config``（kind=criterion|award）、
  ``DELETE .../settlement/config/<criterion|award>/<pk>``；
- **奖项人工发放**：``GET/POST .../awards/grants``、``DELETE .../awards/grants/<pk>``，
  个人奖 → 一个人；集体奖 → 所选公司对应队伍全员；
- 个人奖候选人：``GET .../settlement/candidates?q=``（本比赛全部成员）。

权限口径（需求方确认）：**结算与获奖仅超管可见**（系统超管 / 比赛超管，含读取）；
参赛代表与管理员的获奖记录与电子奖牌经 ``/api/me/awards``、``/api/me/medals`` 在个人档案查看。
"""

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition
from apps.competition.companies.models import Company
from apps.competition.settlement import services as settlement_services
from apps.competition.settlement.models import (
    AwardDefinition, AwardGrant, AwardResult, ScoringCriterion, SettlementRun,
)


def _err(message: str, code: int = 400) -> Response:
    return Response({'code': code, 'message': message, 'details': ''}, status=code)


def _manager_only(request, cid):
    """结算域统一守卫：仅超管可见（含读取）。"""
    if not can_manage_competition(request.user, cid):
        return _err('结算与获奖仅超级管理员可见', 403)
    return None


def _competition(cid):
    from apps.global_.competitions.models import Competition

    return get_object_or_404(Competition, pk=cid)


def _award_def_data(a: AwardDefinition) -> dict:
    return {
        'id': a.id, 'name': a.name, 'kind': a.kind, 'kindLabel': a.get_kind_display(),
        'description': a.description, 'medalLevel': a.medal_level,
    }


def _grant_data(g: AwardGrant) -> dict:
    return {
        'id': g.id,
        'awardId': g.award_id, 'awardName': g.award.name,
        'kind': g.kind, 'kindLabel': g.get_kind_display(),
        'medalLevel': g.award.medal_level,
        'userId': g.user_id, 'userName': g.user_name,
        'companyId': g.company_id, 'companyName': g.company.name if g.company_id else '',
        'recipientCount': g.recipient_count, 'note': g.note,
        'grantedByUsername': g.granted_by_username,
        'grantedAt': g.created_at.isoformat(),
    }


# ---------------------------------------------------------------- 评分准则 / 奖项定义


class ScoringConfigView(APIView):
    """评分准则 + 奖项定义（可配置；奖项由超管设定，人工发放）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        denied = _manager_only(request, cid)
        if denied:
            return denied
        return Response({
            'criteria': [
                {
                    'id': c.id, 'name': c.name, 'fieldKey': c.field_key,
                    'aggregation': c.aggregation, 'direction': c.direction,
                    'weight': c.weight, 'enabled': c.enabled,
                }
                for c in ScoringCriterion.objects.all()
            ],
            'awards': [_award_def_data(a) for a in AwardDefinition.objects.all()],
        })

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err('需要超级管理员权限', 403)
        kind = request.data.get('kind') or 'criterion'
        if kind == 'criterion':
            name = (request.data.get('name') or '').strip()
            field_key = (request.data.get('fieldKey') or '').strip()
            if not name or not field_key:
                return _err('准则名称与字段键必填')
            try:
                weight = float(request.data.get('weight') or 1.0)
            except (TypeError, ValueError):
                return _err('权重必须是数字')
            item = ScoringCriterion.objects.create(
                name=name, field_key=field_key,
                aggregation=request.data.get('aggregation') or ScoringCriterion.Aggregation.SUM,
                direction=request.data.get('direction') or ScoringCriterion.Direction.HIGHER_BETTER,
                weight=weight,
            )
            return Response({'id': item.id}, status=201)

        # 奖项定义
        name = (request.data.get('name') or '').strip()
        if not name:
            return _err('奖项名称必填')
        if len(name) > 100:
            return _err('奖项名称最长 100 个字符')
        # 注意：请求体里 `kind` 是「配置项种类」判别字段（criterion|award），
        # 奖项自身的类型用 `awardKind`（INDIVIDUAL|COLLECTIVE），两者不可同名。
        award_kind = request.data.get('awardKind') or AwardDefinition.Kind.INDIVIDUAL
        if award_kind not in AwardDefinition.Kind.values:
            return _err('奖项类型必须是个人奖或集体奖')
        medal_level = (request.data.get('medalLevel') or '').strip()
        if len(medal_level) > 32:
            return _err('奖牌等级最长 32 个字符')
        if AwardDefinition.objects.filter(name=name, kind=award_kind).exists():
            return _err('同类型下已存在同名奖项')
        item = AwardDefinition.objects.create(
            name=name, kind=award_kind, medal_level=medal_level,
            description=(request.data.get('description') or '').strip(),
        )
        return Response({'id': item.id}, status=201)


class ScoringConfigDeleteView(APIView):
    """删除评分准则 / 奖项定义；删奖项定义会一并撤销它已发放的记录。"""

    permission_classes = [IsAuthenticated]

    def delete(self, request, cid, kind, pk):
        if not can_manage_competition(request.user, cid):
            return _err('需要超级管理员权限', 403)
        if kind == 'criterion':
            ScoringCriterion.objects.filter(pk=pk).delete()
            return Response({'ok': True})
        award = AwardDefinition.objects.filter(pk=pk).first()
        if award is None:
            return Response({'ok': True})
        removed = settlement_services.revoke_award_definition(
            award=award, competition_id=int(cid))
        return Response({'ok': True, 'revokedRecords': removed})


# ---------------------------------------------------------------- 结算


class SettlementRunView(APIView):
    """开始结算（只计算得分与名次；奖项另行人工发放）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err('需要超级管理员权限', 403)
        run = settlement_services.run_settlement(
            competition=_competition(cid), user=request.user)
        return Response({'runId': run.id, 'status': run.status}, status=201)


class SettlementResultView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        denied = _manager_only(request, cid)
        if denied:
            return denied
        run = SettlementRun.objects.filter(status=SettlementRun.Status.SUCCESS).first()
        if run is None:
            return Response({'run': None, 'entries': []})
        return Response({'run': {
            'id': run.id, 'createdAt': run.created_at.isoformat(),
            'criteria': run.criteria_snapshot,
        }, 'entries': (run.result or {}).get('entries') or []})


class AwardListView(APIView):
    """本比赛结算名次（仅超管；奖项改为人工发放，这里只给名次与得分）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        denied = _manager_only(request, cid)
        if denied:
            return denied
        run = SettlementRun.objects.filter(status=SettlementRun.Status.SUCCESS).first()
        if run is None:
            return Response([])
        return Response([
            {
                'companyId': a.company_id, 'companyName': a.company.name,
                'rank': a.rank, 'score': a.score,
            }
            for a in run.awards.select_related('company')
        ])


class AwardCandidateView(APIView):
    """个人奖候选人：本比赛全部成员（可搜索）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        denied = _manager_only(request, cid)
        if denied:
            return denied
        return Response(settlement_services.list_candidates(
            int(cid), request.query_params.get('q') or ''))


# ---------------------------------------------------------------- 奖项发放


class AwardGrantView(APIView):
    """``GET`` 已发放记录；``POST`` 发放（个人奖给一人 / 集体奖给一家公司队伍全员）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        denied = _manager_only(request, cid)
        if denied:
            return denied
        grants = (
            AwardGrant.objects.select_related('award', 'company')
            .order_by('-created_at')[:500]
        )
        return Response([_grant_data(g) for g in grants])

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return _err('需要超级管理员权限', 403)
        award = AwardDefinition.objects.filter(pk=request.data.get('awardId')).first()
        if award is None:
            return _err('奖项不存在，请先在「奖项设置」中创建')

        target_user = None
        company = None
        user_id = request.data.get('userId')
        company_id = request.data.get('companyId')
        if user_id not in (None, ''):
            target_user = get_user_model().objects.filter(pk=user_id).first()
            if target_user is None:
                return _err('获奖人不存在')
        if company_id not in (None, ''):
            company = Company.objects.filter(pk=company_id).first()
            if company is None:
                return _err('公司不存在')

        try:
            grant = settlement_services.grant_award(
                competition=_competition(cid), award=award, granted_by=request.user,
                target_user=target_user, company=company,
                note=request.data.get('note') or '',
            )
        except settlement_services.AwardError as exc:
            return _err(str(exc))

        grant = AwardGrant.objects.select_related('award', 'company').get(pk=grant.id)
        recipients = []
        if grant.kind == AwardGrant.Kind.COLLECTIVE and grant.company_id:
            from apps.global_.profiles.models import AwardRecord

            recipients = [
                {'userId': r.user_id, 'userName': r.user.username}
                for r in AwardRecord.objects.filter(
                    competition_id=int(cid), grant_id=grant.id).select_related('user')
            ]
        elif grant.user_id:
            recipients = [{'userId': grant.user_id, 'userName': grant.user_name}]
        return Response({
            'id': grant.id, 'recipientCount': grant.recipient_count, 'recipients': recipients,
        }, status=201)


class AwardGrantDetailView(APIView):
    """撤销一次发放（回收个人档案里的对应获奖记录）。"""

    permission_classes = [IsAuthenticated]

    def delete(self, request, cid, pk):
        if not can_manage_competition(request.user, cid):
            return _err('需要超级管理员权限', 403)
        grant = AwardGrant.objects.filter(pk=pk).first()
        if grant is None:
            return Response({'ok': True, 'removed': 0})
        removed = settlement_services.revoke_grant(grant=grant, competition_id=int(cid))
        return Response({'ok': True, 'removed': removed})
