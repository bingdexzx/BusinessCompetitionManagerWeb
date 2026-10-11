"""结算服务（§11）：按各公司每财年财务报表 + 评分准则计算评分。

- 指标值取 FINANCE 数据表字段（每财年一行），按评分准则聚合（求和/最新/平均）；
- 归一：min-max 归一到 [0,1]（direction=LOWER_BETTER 取反）；得分 = Σ 权重 × 归一值 × 100；
- 并列：分数相同同名次（并列后跳号）；获奖按 AwardRule 名次区间；
- 结算完成把获奖信息**同步到个人档案**（award_records + 电子奖牌，决策 D12）。
"""

from django.utils import timezone

from apps.competition.companies.models import Company
from apps.competition.industries.models import CompanyFieldValue, IndustryField
from apps.competition.settlement.models import AwardResult, AwardRule, ScoringCriterion, SettlementRun


def _company_metric(company: Company, field_key: str, aggregation: str, finance_fields):
    """取公司在该指标上的聚合值（FINANCE 字段按财年行展开）。"""
    qs = CompanyFieldValue.objects.filter(
        company=company, field_key=field_key, fiscal_year__isnull=False,
    ).order_by('fiscal_year__year')
    values = []
    for row in qs:
        try:
            values.append(float(row.value))
        except (TypeError, ValueError):
            continue
    if not values:
        # 无财年行时回退到无财年行（实体值）或 0
        row = CompanyFieldValue.objects.filter(
            company=company, field_key=field_key, fiscal_year__isnull=True,
        ).first()
        try:
            return float(row.value) if row and row.value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
    if aggregation == ScoringCriterion.Aggregation.LATEST:
        return values[-1]
    if aggregation == ScoringCriterion.Aggregation.AVERAGE:
        return sum(values) / len(values)
    return sum(values)


def run_settlement(*, competition, user=None) -> SettlementRun:
    """执行结算；返回 SettlementRun（含结果与获奖）。须在比赛上下文中。"""
    criteria = [c for c in ScoringCriterion.objects.all() if c.enabled]
    companies = list(Company.objects.filter(status=Company.Status.ACTIVE))
    finance_fields = {
        f.field_key for f in IndustryField.objects.filter(data_table=IndustryField.DataTable.FINANCE)
    }

    raw = {}   # companyId -> {criterionId: value}
    for company in companies:
        raw[company.id] = {
            c.id: _company_metric(company, c.field_key, c.aggregation, finance_fields)
            for c in criteria
        }

    # min-max 归一
    scored = []
    for company in companies:
        total, detail = 0.0, {}
        for c in criteria:
            values = [raw[co.id][c.id] for co in companies]
            lo, hi = min(values), max(values)
            norm = 0.5 if hi == lo else (raw[company.id][c.id] - lo) / (hi - lo)
            if c.direction == ScoringCriterion.Direction.LOWER_BETTER:
                norm = 1 - norm
            contrib = c.weight * norm * 100
            total += contrib
            detail[c.name] = {
                'value': raw[company.id][c.id], 'normalized': round(norm, 4),
                'weight': c.weight, 'score': round(contrib, 2),
            }
        scored.append({'company': company, 'score': round(total, 2), 'detail': detail})

    # 排名（并列同名次、跳号）
    scored.sort(key=lambda r: -r['score'])
    rank, prev_score = 0, None
    for i, row in enumerate(scored, start=1):
        if prev_score is None or row['score'] != prev_score:
            rank = i
            prev_score = row['score']
        row['rank'] = rank

    rules = list(AwardRule.objects.all())
    for row in scored:
        row['awardLevel'] = ''
        for rule in rules:
            if rule.rank_from <= row['rank'] <= rule.rank_to:
                row['awardLevel'] = rule.award_level
                row['medalLevel'] = rule.medal_level or rule.award_level
                break

    run = SettlementRun.objects.create(
        status=SettlementRun.Status.SUCCESS,
        criteria_snapshot=[
            {'id': c.id, 'name': c.name, 'fieldKey': c.field_key, 'aggregation': c.aggregation,
             'direction': c.direction, 'weight': c.weight}
            for c in criteria
        ],
        result={'entries': [
            {'companyId': r['company'].id, 'companyName': r['company'].name,
             'rank': r['rank'], 'score': r['score'], 'awardLevel': r.get('awardLevel', ''),
             'detail': r['detail']}
            for r in scored
        ]},
        created_by=getattr(user, 'id', None),
        created_by_username=getattr(user, 'username', ''),
        finished_at=timezone.now(),
    )
    for r in scored:
        AwardResult.objects.create(
            settlement_run=run, company=r['company'], rank=r['rank'], score=r['score'],
            award_level=r.get('awardLevel', ''), detail=r['detail'],
        )

    sync_awards_to_profiles(run, competition)
    return run


def sync_awards_to_profiles(run: SettlementRun, competition):
    """比赛信息、获奖信息同步到个人信息（§11：查看记录、电子奖牌）。"""
    from apps.global_.profiles.models import AwardRecord, MedalAsset
    from apps.global_.teams.models import Team, TeamMember

    competition_name = competition.name
    for award in run.awards.select_related('company'):
        team = Team.objects.filter(pk=award.company.team_id).first() if award.company.team_id else None
        users = []
        if team is not None:
            users = [m.user for m in team.members.select_related('user')]
        else:
            # 无队伍映射时，管理员/超管也可查看（不写个人档案）
            users = []
        medal = None
        if award.award_level:
            medal = MedalAsset.objects.filter(award_level=award.award_level).first()
            if medal is None:
                medal = MedalAsset.objects.create(
                    award_level=award.award_level,
                    display_name=f'{award.award_level}电子奖牌',
                    display_asset=_default_medal_svg(award.award_level),
                )
        for user in users:
            AwardRecord.objects.update_or_create(
                user=user, competition_id=competition.id,
                defaults={
                    'competition_name': competition_name,
                    'team_name': award.company.name,
                    'rank': award.rank,
                    'award_level': award.award_level,
                    'score': award.score,
                    'medal': medal,
                    'detail': {'settlementRunId': run.id, 'metrics': award.detail},
                },
            )


_MEDAL_COLORS = {
    '一等奖': ('#f6c445', '#d99e2b'),
    '二等奖': ('#cfd6e4', '#9aa7bd'),
    '三等奖': ('#d9a066', '#b0763c'),
}


def _default_medal_svg(award_level: str) -> str:
    """默认电子奖牌样式（仅在线展示，决策 D12）。"""
    fill, stroke = _MEDAL_COLORS.get(award_level, ('#8ecae6', '#219ebc'))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        f'<circle cx="60" cy="60" r="52" fill="{fill}" stroke="{stroke}" stroke-width="6"/>'
        f'<circle cx="60" cy="60" r="38" fill="none" stroke="{stroke}" stroke-width="2"/>'
        f'<text x="60" y="70" font-size="22" text-anchor="middle" fill="{stroke}">'
        f'{award_level}</text></svg>'
    )
