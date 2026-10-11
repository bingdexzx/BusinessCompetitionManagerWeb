"""财年编排（§10.2 财年编排、§6.2 fiscal_year_backups）。

| 步骤 | 行为 |
|------|------|
| 开启财年 | 创建 FiscalYear(OPEN)，触发产业字段**财年定时器**（FY_START） |
| 结束财年 | FiscalYear(CLOSED) → **自动备份一次各公司字段数据表** + FY_END 定时器 |
| 补录 | 以所补录财年末备份快照为执行基准（决策 D14，engine._backup_basis） |
"""

from django.db import transaction
from django.utils import timezone

from apps.common import context as ctx
from apps.competition.companies.models import Company
from apps.competition.fieldlogs.models import FieldLog
from apps.competition.fiscal.models import FiscalYear, FiscalYearBackup
from apps.competition.industries.models import CompanyFieldValue, IndustryField


class FiscalError(Exception):
    pass


def comp_atomic():
    """比赛库事务（多库架构下事务必须落在比赛库连接上，§5.2）。"""
    return transaction.atomic(using=(ctx.get_competition_alias() or 'default'))


def open_fiscal_year(*, user) -> FiscalYear:
    """开启财年（超级管理员）：触发 FY_START 财年定时器字段。"""
    if FiscalYear.objects.filter(status=FiscalYear.Status.OPEN).exists():
        raise FiscalError('已有进行中的财年')
    last = FiscalYear.objects.order_by('-year').first()
    with comp_atomic():
        fy = FiscalYear.objects.create(year=(last.year + 1) if last else 1)
        _run_timers(fy, trigger=IndustryField.TimerTrigger.FY_START, user=user)
    return fy


def close_fiscal_year(*, user) -> FiscalYear:
    """结束财年：自动备份一次各公司字段数据表（实体信息表 + 财务报表整表快照）。"""
    fy = FiscalYear.objects.filter(status=FiscalYear.Status.OPEN).first()
    if fy is None:
        raise FiscalError('没有进行中的财年')
    with comp_atomic():
        _run_timers(fy, trigger=IndustryField.TimerTrigger.FY_END, user=user)
        _backup_all(fy)
        fy.status = FiscalYear.Status.CLOSED
        fy.closed_at = timezone.now()
        fy.save(update_fields=['status', 'closed_at'])
    return fy


def _backup_all(fy: FiscalYear):
    for company in Company.objects.all():
        snapshot = {}
        for row in CompanyFieldValue.objects.filter(company=company, fiscal_year__in=[fy, None]):
            if row.fiscal_year_id == fy.id:
                snapshot[row.field_key] = row.value
            else:
                snapshot.setdefault(row.field_key, row.value)
        FiscalYearBackup.objects.update_or_create(
            fiscal_year=fy, company=company, defaults={'snapshot': snapshot},
        )


def _run_timers(fy: FiscalYear, *, trigger, user):
    """财年定时器字段（§6.2 timerEnabled/timerTrigger）：公式级联重算 + 字段日志 FY_TIMER。"""
    from apps.competition.industries.services import recompute_company_fields

    fields = list(IndustryField.objects.filter(timer_enabled=True, timer_trigger=trigger))
    if not fields:
        return
    for company in Company.objects.all():
        for field in fields:
            before = _value(company, field.field_key, fy)
            recompute_company_fields(company, fiscal_year=fy, only_keys={field.field_key})
            after = _value(company, field.field_key, fy)
            if after != before:
                FieldLog.objects.create(
                    company=company, field_key=field.field_key,
                    data_table=field.data_table, event=FieldLog.Event.VALUE_CHANGE,
                    op='SET', before_raw=before, after_raw=after,
                    source=FieldLog.Source.FY_TIMER, round_no=0,
                    operator_id=getattr(user, 'id', None),
                    operator_username=getattr(user, 'username', ''),
                )


def _value(company, field_key, fy):
    row = CompanyFieldValue.objects.filter(
        company=company, field_key=field_key, fiscal_year=fy).first()
    if row is None:
        row = CompanyFieldValue.objects.filter(
            company=company, field_key=field_key, fiscal_year__isnull=True).first()
    return row.value if row else None
