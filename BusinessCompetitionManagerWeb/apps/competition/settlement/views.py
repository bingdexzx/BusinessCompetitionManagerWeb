"""结算 API（§12：POST .../settlement/run、GET .../settlement/result、GET .../awards）。"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.authority import can_manage_competition, user_company_ids
from apps.competition.settlement import services as settlement_services
from apps.competition.settlement.models import AwardResult, AwardRule, ScoringCriterion, SettlementRun


class ScoringConfigView(APIView):
    """评分准则 / 获奖规则配置（可配置评分引擎，决策 D11）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        return Response({
            'criteria': [
                {
                    'id': c.id, 'name': c.name, 'fieldKey': c.field_key,
                    'aggregation': c.aggregation, 'direction': c.direction,
                    'weight': c.weight, 'enabled': c.enabled,
                }
                for c in ScoringCriterion.objects.all()
            ],
            'awardRules': [
                {
                    'id': r.id, 'awardLevel': r.award_level,
                    'rankFrom': r.rank_from, 'rankTo': r.rank_to,
                    'medalLevel': r.medal_level,
                }
                for r in AwardRule.objects.all()
            ],
        })

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '需要超级管理员权限', 'details': ''}, status=403)
        kind = request.data.get('kind') or 'criterion'
        if kind == 'criterion':
            item = ScoringCriterion.objects.create(
                name=request.data.get('name') or '',
                field_key=request.data.get('fieldKey') or '',
                aggregation=request.data.get('aggregation') or ScoringCriterion.Aggregation.SUM,
                direction=request.data.get('direction') or ScoringCriterion.Direction.HIGHER_BETTER,
                weight=float(request.data.get('weight') or 1.0),
            )
            return Response({'id': item.id}, status=201)
        item = AwardRule.objects.create(
            award_level=request.data.get('awardLevel') or '',
            rank_from=int(request.data.get('rankFrom') or 1),
            rank_to=int(request.data.get('rankTo') or 1),
            medal_level=request.data.get('medalLevel') or '',
        )
        return Response({'id': item.id}, status=201)


class ScoringConfigDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, cid, kind, pk):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '需要超级管理员权限', 'details': ''}, status=403)
        model = ScoringCriterion if kind == 'criterion' else AwardRule
        model.objects.filter(pk=pk).delete()
        return Response({'ok': True})


class SettlementRunView(APIView):
    """开始结算（§2.2 阶段六：按每财年财务报表 + 评分准则计算评分）。"""

    permission_classes = [IsAuthenticated]

    def post(self, request, cid):
        if not can_manage_competition(request.user, cid):
            return Response({'code': 403, 'message': '需要超级管理员权限', 'details': ''}, status=403)
        from django.shortcuts import get_object_or_404
        from apps.global_.competitions.models import Competition
        competition = get_object_or_404(Competition, pk=cid)
        run = settlement_services.run_settlement(
            competition=competition, user=request.user)
        return Response({'runId': run.id, 'status': run.status}, status=201)


class SettlementResultView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        run = SettlementRun.objects.filter(status=SettlementRun.Status.SUCCESS).first()
        if run is None:
            return Response({'run': None, 'entries': []})
        ids = user_company_ids(request.user)
        entries = (run.result or {}).get('entries') or []
        if '*' not in ids:
            entries = [e for e in entries if e.get('companyId') in ids]
        return Response({'run': {
            'id': run.id, 'createdAt': run.created_at.isoformat(),
            'criteria': run.criteria_snapshot,
        }, 'entries': entries})


class AwardListView(APIView):
    """本比赛获奖信息（§12：GET .../awards）。"""

    permission_classes = [IsAuthenticated]

    def get(self, request, cid):
        run = SettlementRun.objects.filter(status=SettlementRun.Status.SUCCESS).first()
        if run is None:
            return Response([])
        return Response([
            {
                'companyId': a.company_id, 'companyName': a.company.name,
                'rank': a.rank, 'score': a.score, 'awardLevel': a.award_level,
            }
            for a in run.awards.select_related('company')
        ])
