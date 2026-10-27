"""结算服务（§11；2026-10 需求变更）。

- **结算 = 只算分**：按各公司每财年财务报表字段 + 评分准则（聚合/方向/权重）
  min-max 归一求总分 → 名次（并列同名次、跳号）。**不再自动评奖、不再自动写档案**。
- **奖项人工发放**：
  - 个人奖 → 指定一个人，其个人档案记一条获奖记录；
  - 集体奖 → 指定一家公司，该公司**对应队伍的全员**各记一条获奖记录；
  - 发放落库为 ``AwardGrant``（比赛库），并按 ``grant_id`` 写入全局库 ``AwardRecord``，
    因此撤销可按发放记录精确回收（不影响其他奖项）。
"""

from django.db.models import Q
from django.utils import timezone

from apps.competition.companies.models import Company
from apps.competition.industries.models import CompanyFieldValue
from apps.competition.settlement.models import (
    AwardDefinition, AwardGrant, AwardResult, ScoringCriterion, SettlementRun,
)

# 个人奖候选人单次返回上限（搜索框用，避免一次拉全量）
CANDIDATE_LIMIT = 300


class AwardError(Exception):
    """奖项发放/撤销的业务错误（视图映射为 400）。"""


# ================================================================ 结算（只算分）


def _company_metric(company: Company, field_key: str, aggregation: str):
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
    """执行结算（只计算得分与名次）；返回 SettlementRun。须在比赛上下文中。"""
    criteria = [c for c in ScoringCriterion.objects.all() if c.enabled]
    companies = list(Company.objects.filter(status=Company.Status.ACTIVE))

    raw = {}   # companyId -> {criterionId: value}
    for company in companies:
        raw[company.id] = {
            c.id: _company_metric(company, c.field_key, c.aggregation) for c in criteria
        }

    # min-max 归一 → 加权总分
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

    run = SettlementRun.objects.create(
        status=SettlementRun.Status.SUCCESS,
        criteria_snapshot=[
            {'id': c.id, 'name': c.name, 'fieldKey': c.field_key, 'aggregation': c.aggregation,
             'direction': c.direction, 'weight': c.weight}
            for c in criteria
        ],
        result={'entries': [
            {'companyId': r['company'].id, 'companyName': r['company'].name,
             'rank': r['rank'], 'score': r['score'], 'detail': r['detail']}
            for r in scored
        ]},
        created_by=getattr(user, 'id', None),
        created_by_username=getattr(user, 'username', ''),
        finished_at=timezone.now(),
    )
    for r in scored:
        AwardResult.objects.create(
            settlement_run=run, company=r['company'], rank=r['rank'],
            score=r['score'], detail=r['detail'],
        )
    return run


# ================================================================ 奖项发放


def company_recipient_ids(company: Company | None) -> list:
    """公司对应队伍的**全员**用户 ID（集体奖受益范围）。

    公司由队伍映射而来（``Company.team_id``）：取该队伍全部成员。
    无队伍映射/队伍无成员时返回空列表（发放会被拒绝，避免"发了但没人"）。
    """
    if company is None or not company.team_id:
        return []
    from apps.global_.teams.models import Team

    team = Team.objects.filter(pk=company.team_id).first()
    if team is None:
        return []
    return list(team.members.values_list('user_id', flat=True))


def list_candidates(competition_id: int, keyword: str = '') -> list:
    """个人奖候选人：本比赛全部成员（可按用户名/显示名搜索）+ 所属公司名。"""
    from apps.global_.memberships.models import CompetitionMembership
    from apps.global_.teams.models import TeamMember

    qs = (
        CompetitionMembership.objects
        .filter(competition_id=competition_id, is_active=True)
        .select_related('user')
        .order_by('user__username')
    )
    keyword = (keyword or '').strip()
    if keyword:
        qs = qs.filter(
            Q(user__username__icontains=keyword) | Q(user__display_name__icontains=keyword))

    # 用户 → 所属公司（该比赛内，取其队伍映射的公司；一人多队时取第一个）
    user_company: dict = {}
    for uid, company_id in (
        TeamMember.objects.filter(team__competition_id=competition_id)
        .values_list('user_id', 'team__company_id')
    ):
        if company_id and uid not in user_company:
            user_company[uid] = company_id
    names = {
        c.id: c.name
        for c in Company.objects.filter(pk__in=set(user_company.values()))
    }

    out = []
    for m in qs[:CANDIDATE_LIMIT]:
        company_id = user_company.get(m.user_id)
        out.append({
            'userId': m.user_id,
            'username': m.user.username,
            'displayName': m.user.display_name or m.user.username,
            'companyId': company_id,
            'companyName': names.get(company_id, '') if company_id else '',
        })
    return out


def _medal_for(award: AwardDefinition):
    """奖项配置了奖牌等级时，取/建对应电子奖牌；未配置返回 None。"""
    if not award.medal_level:
        return None
    from apps.global_.profiles.models import MedalAsset

    medal = MedalAsset.objects.filter(award_level=award.medal_level).first()
    if medal is None:
        medal = MedalAsset.objects.create(
            award_level=award.medal_level,
            display_name=f'{award.medal_level}电子奖牌',
            display_asset=_default_medal_svg(award.medal_level),
        )
    return medal


def _write_profile_records(*, grant, award, competition, medal, recipients) -> int:
    """把一次发放写入各受益人的个人档案；返回写入条数。"""
    from apps.global_.profiles.models import AwardRecord

    written = 0
    for user_id, user_name, company_name in recipients:
        AwardRecord.objects.update_or_create(
            user_id=user_id, competition_id=competition.id, grant_id=grant.id,
            defaults={
                'competition_name': competition.name,
                'team_name': company_name,
                'award_name': award.name,
                'award_kind': award.kind,
                'medal': medal,
                'detail': {'source': 'MANUAL', 'awardId': award.id, 'note': grant.note},
            },
        )
        written += 1
    return written


def grant_award(*, competition, award: AwardDefinition, granted_by=None,
                target_user=None, company: Company | None = None, note: str = '') -> AwardGrant:
    """发放一次奖项（个人奖给一个人；集体奖给一家公司的队伍全员）。"""
    from django.contrib.auth import get_user_model

    note = (note or '').strip()
    if award.kind == AwardDefinition.Kind.INDIVIDUAL:
        if target_user is None:
            raise AwardError('个人奖必须指定获奖人')
        if company is not None:
            raise AwardError('个人奖不能指定公司')
        recipients = [(target_user.id, target_user.username, '')]
        grant = AwardGrant.objects.create(
            award=award, kind=AwardGrant.Kind.INDIVIDUAL,
            user_id=target_user.id, user_name=target_user.username,
            recipient_count=1, note=note,
            granted_by=getattr(granted_by, 'id', None),
            granted_by_username=getattr(granted_by, 'username', ''),
        )
    else:
        if company is None:
            raise AwardError('集体奖必须指定公司')
        if target_user is not None:
            raise AwardError('集体奖不能指定个人')
        user_ids = company_recipient_ids(company)
        if not user_ids:
            raise AwardError(f'公司「{company.name}」没有对应队伍成员，无法发放集体奖')
        users = list(get_user_model().objects.filter(pk__in=user_ids))
        recipients = [(u.id, u.username, company.name) for u in users]
        grant = AwardGrant.objects.create(
            award=award, kind=AwardGrant.Kind.COLLECTIVE, company=company,
            recipient_count=len(recipients), note=note,
            granted_by=getattr(granted_by, 'id', None),
            granted_by_username=getattr(granted_by, 'username', ''),
        )

    medal = _medal_for(award)
    grant.recipient_count = _write_profile_records(
        grant=grant, award=award, competition=competition, medal=medal, recipients=recipients)
    grant.save(update_fields=['recipient_count'])
    return grant


def _delete_profile_records(competition_id: int, grant_ids: list) -> int:
    """按发放记录回收个人档案里的获奖记录；返回删除条数。"""
    from apps.global_.profiles.models import AwardRecord

    if not grant_ids:
        return 0
    deleted, _ = AwardRecord.objects.filter(
        competition_id=competition_id, grant_id__in=grant_ids).delete()
    return deleted


def revoke_grant(*, grant: AwardGrant, competition_id: int) -> int:
    """撤销一次发放：先回收档案记录，再删除发放记录。"""
    removed = _delete_profile_records(competition_id, [grant.id])
    grant.delete()
    return removed


def revoke_award_definition(*, award: AwardDefinition, competition_id: int) -> int:
    """删除奖项定义前，先回收它所有已发放记录（避免档案里留下无主奖项）。"""
    grant_ids = list(award.grants.values_list('id', flat=True))
    removed = _delete_profile_records(competition_id, grant_ids)
    award.delete()
    return removed


# ================================================================ 电子奖牌样式


_MEDAL_COLORS = {
    '一等奖': ('#f6c445', '#d99e2b'),
    '二等奖': ('#cfd6e4', '#9aa7bd'),
    '三等奖': ('#d9a066', '#b0763c'),
}


def _default_medal_svg(award_level: str) -> str:
    """默认电子奖牌样式（仅在线展示）。"""
    fill, stroke = _MEDAL_COLORS.get(award_level, ('#8ecae6', '#219ebc'))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
        f'<circle cx="60" cy="60" r="52" fill="{fill}" stroke="{stroke}" stroke-width="6"/>'
        f'<circle cx="60" cy="60" r="38" fill="none" stroke="{stroke}" stroke-width="2"/>'
        f'<text x="60" y="70" font-size="22" text-anchor="middle" fill="{stroke}">'
        f'{award_level}</text></svg>'
    )
