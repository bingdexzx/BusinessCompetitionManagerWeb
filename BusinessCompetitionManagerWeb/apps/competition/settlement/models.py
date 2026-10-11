"""结算、评分与获奖（§11、决策 D11）。

- **输入**：各公司**每财年财务报表**（finance 表字段值 + 财年备份）；
- **评分准则**：可配置评分引擎——指标（财务报表字段）、聚合方式、权重、归一方式、
  并列规则（细则待需求方提供，框架先落地）；
- **输出**：比赛名次与获奖信息 → 同步个人档案 + **电子奖牌（仅在线展示）**。
"""

from django.db import models


class ScoringCriterion(models.Model):
    """评分准则（可配置框架，决策 D11）。"""

    class Aggregation(models.TextChoices):
        SUM = 'SUM', '各财年求和'
        LATEST = 'LATEST', '最新财年值'
        AVERAGE = 'AVERAGE', '各财年平均'

    class Direction(models.TextChoices):
        HIGHER_BETTER = 'HIGHER_BETTER', '越高越好'
        LOWER_BETTER = 'LOWER_BETTER', '越低越好'

    name = models.CharField('指标名称', max_length=100)
    field_key = models.CharField('财务报表字段', max_length=64)
    aggregation = models.CharField('聚合方式', max_length=16, choices=Aggregation.choices,
                                   default=Aggregation.SUM)
    direction = models.CharField('方向', max_length=16, choices=Direction.choices,
                                 default=Direction.HIGHER_BETTER)
    weight = models.FloatField('权重', default=1.0)
    enabled = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '评分准则'
        verbose_name_plural = '评分准则'
        ordering = ['id']


class AwardRule(models.Model):
    """获奖规则：名次区间 → 获奖等级（并列名次按分数并列后跳号）。"""

    award_level = models.CharField('获奖等级', max_length=32)  # 一等奖 / 二等奖 ...
    rank_from = models.PositiveIntegerField('起始名次', default=1)
    rank_to = models.PositiveIntegerField('结束名次', default=1)
    medal_level = models.CharField('电子奖牌等级', max_length=32, blank=True)

    class Meta:
        verbose_name = '获奖规则'
        verbose_name_plural = '获奖规则'
        ordering = ['rank_from']


class SettlementRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', '待运行'
        SUCCESS = 'SUCCESS', '已完成'
        FAILED = 'FAILED', '失败'

    status = models.CharField('状态', max_length=16, choices=Status.choices, default=Status.PENDING)
    criteria_snapshot = models.JSONField('评分准则快照', default=list, blank=True)
    result = models.JSONField('结算结果', default=dict, blank=True)
    created_by = models.BigIntegerField('操作者（全局库用户 ID）', null=True, blank=True)
    created_by_username = models.CharField('操作者用户名', max_length=150, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    finished_at = models.DateTimeField('完成时间', null=True, blank=True)

    class Meta:
        verbose_name = '结算'
        verbose_name_plural = '结算'
        ordering = ['-created_at']


class AwardResult(models.Model):
    """单个公司的名次与获奖（结算输出）。"""

    settlement_run = models.ForeignKey(SettlementRun, on_delete=models.CASCADE, related_name='awards')
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='awards')
    rank = models.PositiveIntegerField('名次')
    score = models.FloatField('得分')
    award_level = models.CharField('获奖等级', max_length=32, blank=True)
    detail = models.JSONField('指标明细', default=dict, blank=True)

    class Meta:
        verbose_name = '获奖结果'
        verbose_name_plural = '获奖结果'
        ordering = ['rank']
        constraints = [
            models.UniqueConstraint(fields=['settlement_run', 'company'], name='uniq_run_company_award'),
        ]
