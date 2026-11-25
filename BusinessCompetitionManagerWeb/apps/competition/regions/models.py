"""区域与消费者需求（比赛域）。

旧系统 `apps.regions` / `apps.consumer_demands` 的恢复实现（2026-10 决策：补齐）：
- Region：区域实体（地图节点 region 归属、区域总览卡片配置 overview_cards）；
- ConsumerDemand：按区域的消费者需求，变更后触发所在区域公司公式字段重算
  （旧 `_recompute_dependent_fields` 语义，公式可引用 `consumerDemand` 特殊键）。
- RegionField / RegionFieldValue：**区域字段**（2026-11 新增）。字段定义挂在区域上，
  值也按区域存；只有满足字段配置条件的公司才能通过合同修改该值（超级管理员可手工改）。
  区域字段属于实体信息表，不按财年存值。
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


class RegionField(models.Model):
    """区域字段定义（2026-11：**比赛级、由比赛包定义**，所有区域共用同一套字段）。

    ``condition`` 是附加条件（公司实体字段比较）；默认规则是公司「所在区域」= 区域名
    才允许通过合同修改该区域字段值。字段值按区域存（RegionFieldValue）。
    """

    class FieldType(models.TextChoices):
        NUMBER = 'NUMBER', '数值'
        TEXT = 'TEXT', '文本'
        BOOL = 'BOOL', '布尔'
        DATE = 'DATE', '日期'

    field_key = models.CharField('字段键', max_length=64, unique=True)
    name = models.CharField('字段名', max_length=100)
    field_type = models.CharField(
        '数据类型', max_length=16, choices=FieldType.choices, default=FieldType.NUMBER)
    default_value = models.JSONField('初始值', null=True, blank=True)
    condition = models.JSONField('附加修改条件', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '区域字段'
        verbose_name_plural = '区域字段'
        db_table = 'region_fields'
        ordering = ['id']

    def __str__(self):
        return self.field_key


class RegionFieldValue(models.Model):
    """区域字段值（按区域存，实体字段不分财年）。"""

    region = models.ForeignKey(
        Region, verbose_name='区域', on_delete=models.CASCADE, related_name='field_values')
    field_key = models.CharField('字段键', max_length=64)
    value = models.JSONField('值', null=True, blank=True)
    version = models.BigIntegerField('版本（乐观锁）', default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '区域字段值'
        verbose_name_plural = '区域字段值'
        db_table = 'region_field_values'
        ordering = ['region_id', 'field_key']
        constraints = [
            models.UniqueConstraint(
                fields=['region', 'field_key'], name='uniq_region_field_value'),
        ]
