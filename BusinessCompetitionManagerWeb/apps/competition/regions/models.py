"""区域与消费者需求（比赛域）。

旧系统 `apps.regions` / `apps.consumer_demands` 的恢复实现（2026-10 决策：补齐）：
- Region：区域实体（地图节点 region 归属、区域总览卡片配置 overview_cards）；
- ConsumerDemand：按区域的消费者需求，变更后触发所在区域公司公式字段重算
  （旧 `_recompute_dependent_fields` 语义，公式可引用 `consumerDemand` 特殊键）。
"""

from django.db import models


class Region(models.Model):
    """区域（比赛级）。比赛库模型，随比赛库迁移生命周期。"""

    name = models.CharField('区域名称', max_length=128)
    description = models.TextField('描述', blank=True, default='')
    # 总览卡片配置：[{id, displayName, companyId, industryFieldKey, zone?}]（industryFieldId 为旧键，写时归一到 industryFieldKey）
    overview_cards = models.JSONField('总览卡片', default=list, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '区域'
        verbose_name_plural = '区域'
        db_table = 'regions'
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_region_name'),
        ]

    def __str__(self):
        return self.name


class ConsumerDemand(models.Model):
    """消费者需求（比赛级，按区域）。

    product_name 冗余存储产品名（旧系统 `product_type` 字段的语义）：
    产品被删除后列表仍可展示与留痕。
    """

    region = models.ForeignKey(
        Region, verbose_name='区域', on_delete=models.CASCADE, related_name='demands')
    product = models.ForeignKey(
        'basedata.Product', verbose_name='产品', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='consumer_demands')
    product_name = models.CharField('产品名（冗余）', max_length=128, blank=True, default='')
    quantity = models.IntegerField('数量', default=0)
    note = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '消费者需求'
        verbose_name_plural = '消费者需求'
        db_table = 'consumer_demands'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['region', 'updated_at']),
        ]

    def __str__(self):
        return f'{self.region_id}-{self.product_name}'
