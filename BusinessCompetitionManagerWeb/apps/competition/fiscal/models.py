"""财年与备份（§6.2 fiscal_years / fiscal_year_backups、§10.2 财年编排）。

- 开启财年 → 触发财年定时器（FY_START）；
- 结束财年 → **自动备份一次各公司字段数据表**（实体信息表 + 财务报表整表快照）；
- 补录合同以「所补录财年末备份快照」为执行基准（决策 D14）。
"""

from django.db import models


class FiscalYear(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', '进行中'
        CLOSED = 'CLOSED', '已结束'
        BACKFILL = 'BACKFILL', '补录期'

    year = models.PositiveIntegerField('财年序号')
    status = models.CharField('状态', max_length=16, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField('开启时间', auto_now_add=True)
    closed_at = models.DateTimeField('结束时间', null=True, blank=True)

    class Meta:
        verbose_name = '财年'
        verbose_name_plural = '财年'
        constraints = [models.UniqueConstraint(fields=['year'], name='uniq_fiscal_year')]
        ordering = ['year']


class FiscalYearBackup(models.Model):
    """结束财年自动备份的各公司字段数据表快照。"""

    fiscal_year = models.ForeignKey(FiscalYear, on_delete=models.CASCADE, related_name='backups')
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='fiscal_backups')
    snapshot = models.JSONField('快照（实体信息表+财务报表）', default=dict)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '财年备份'
        verbose_name_plural = '财年备份'
        constraints = [
            models.UniqueConstraint(fields=['fiscal_year', 'company'], name='uniq_fiscal_company_backup'),
        ]
