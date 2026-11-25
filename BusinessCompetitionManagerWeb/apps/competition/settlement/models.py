"""结算、评分与获奖（§11、决策 D11；2026-10 需求变更）。

- **结算只算分**：输入 = 各公司**每财年财务报表**（finance 表字段值），
  按评分准则（指标/聚合/权重/方向）min-max 归一求总分 → 名次；
  **不再按名次自动评奖**。
- **奖项人工设定 + 人工发放**：超级管理员维护「奖项定义」（个人奖 / 集体奖，可选奖牌等级），
  再对**具体人**（个人奖）或**具体公司**（集体奖 = 该公司队伍全员）发放；
  发放结果写入个人档案 AwardRecord（可撤销）。
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


class AwardDefinition(models.Model):
    """奖项定义（每比赛，由超级管理员维护）：个人奖 / 集体奖，人工发放。

    ``medal_level`` 可选：填写时发放会给获奖人挂上对应「电子奖牌」样式
    （apps.global_.profiles.MedalAsset.award_level）。
    """

    class Kind(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', '个人奖'
        COLLECTIVE = 'COLLECTIVE', '集体奖'

    name = models.CharField('奖项名称', max_length=100)
    kind = models.CharField('类型', max_length=16, choices=Kind.choices, default=Kind.INDIVIDUAL)
    description = models.TextField('说明', blank=True, default='')
    medal_level = models.CharField('奖牌等级（可选）', max_length=32, blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '奖项定义'
        verbose_name_plural = '奖项定义'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['name', 'kind'], name='uniq_award_def_name_kind'),
        ]

    def __str__(self):
        return f'{self.name}（{self.get_kind_display()}）'


class AwardGrant(models.Model):
    """一次发放记录：个人奖 = 1 人；集体奖 = 所选公司对应队伍的全员。"""

    class Kind(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', '个人奖'
        COLLECTIVE = 'COLLECTIVE', '集体奖'

    award = models.ForeignKey(
        AwardDefinition, verbose_name='奖项', on_delete=models.CASCADE, related_name='grants')
    kind = models.CharField('类型', max_length=16, choices=Kind.choices)
    # 个人奖：获奖人（全局库用户 ID，跨库只存整数）
    user_id = models.BigIntegerField('获奖人（全局库用户 ID）', null=True, blank=True)
    user_name = models.CharField('获奖人用户名', max_length=150, blank=True, default='')
    # 集体奖：获奖公司（比赛库内，可建外键）
    company = models.ForeignKey(
        'companies.Company', verbose_name='获奖公司', null=True, blank=True,
        on_delete=models.CASCADE, related_name='award_grants')
    recipient_count = models.PositiveIntegerField('受益人数', default=0)
    note = models.TextField('备注', blank=True, default='')
    granted_by = models.BigIntegerField('发放人（全局库用户 ID）', null=True, blank=True)
    granted_by_username = models.CharField('发放人用户名', max_length=150, blank=True, default='')
    created_at = models.DateTimeField('发放时间', auto_now_add=True)

    class Meta:
        verbose_name = '奖项发放'
        verbose_name_plural = '奖项发放'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['award', 'created_at'])]

    def __str__(self):
        who = self.user_name or (self.company.name if self.company_id else '')
        return f'{self.award.name} → {who}'


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
    """单个公司的结算名次与得分（结算输出；奖项改为人工发放，不再自动评级）。"""

    settlement_run = models.ForeignKey(SettlementRun, on_delete=models.CASCADE, related_name='awards')
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE, related_name='awards')
    rank = models.PositiveIntegerField('名次')
    score = models.FloatField('得分')
    detail = models.JSONField('指标明细', default=dict, blank=True)

    class Meta:
        verbose_name = '获奖结果'
        verbose_name_plural = '获奖结果'
        ordering = ['rank']
        constraints = [
            models.UniqueConstraint(fields=['settlement_run', 'company'], name='uniq_run_company_award'),
        ]
