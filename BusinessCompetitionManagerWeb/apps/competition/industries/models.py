"""产业字段定义与字段值（§6.2 industry_fields / company_field_values、§6.3 实体信息表/财务报表）。

- 字段定义由**产业类型 Python 插件**生成（§8.2），字段变化只对**本比赛库**迁移；
- ``dataTable`` 决定归属：ENTITY（实体信息表）/ FINANCE（财务报表）；
- 财务报表按 **财年 × 字段** 组织：FINANCE 行带 ``fiscal_year`` 维度。
"""

from django.db import models


class IndustryField(models.Model):
    class DataTable(models.TextChoices):
        ENTITY = 'ENTITY', '实体信息表'
        FINANCE = 'FINANCE', '财务报表'

    class FieldType(models.TextChoices):
        NUMBER = 'NUMBER', '数值'
        TEXT = 'TEXT', '文本'
        BOOL = 'BOOL', '布尔'
        REF = 'REF', '引用'
        DATE = 'DATE', '日期'

    class TimerTrigger(models.TextChoices):
        FY_START = 'FY_START', '财年开始'
        FY_END = 'FY_END', '财年结束'

    field_key = models.CharField('字段键', max_length=64)
    name = models.CharField('字段名', max_length=100)
    field_type = models.CharField('数据类型', max_length=16, choices=FieldType.choices, default=FieldType.NUMBER)
    default_value = models.JSONField('初始值', null=True, blank=True)
    formula = models.CharField('公式', max_length=500, blank=True)
    data_table = models.CharField(
        '数据表归属', max_length=16, choices=DataTable.choices, default=DataTable.ENTITY,
    )
    is_calculated = models.BooleanField('公式计算字段', default=False)
    timer_enabled = models.BooleanField('财年定时器', default=False)
    timer_trigger = models.CharField(
        '定时器触发', max_length=16, choices=TimerTrigger.choices, blank=True,
    )
    industry_key = models.CharField('产业类型', max_length=64, blank=True)
    plugin_key = models.CharField('来源插件', max_length=64, blank=True)
    plugin_version = models.CharField('插件版本', max_length=32, blank=True)
    meta = models.JSONField('扩展元数据', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '产业字段'
        verbose_name_plural = '产业字段'
        constraints = [
            models.UniqueConstraint(fields=['field_key'], name='uniq_industry_field_key'),
        ]

    def __str__(self):
        return f'{self.field_key} ({self.data_table})'


class CompanyFieldValue(models.Model):
    """字段值统一存储；按字段定义的 dataTable 区分实体信息表 / 财务报表视图。"""

    company = models.ForeignKey(
        'companies.Company', verbose_name='公司',
        on_delete=models.CASCADE, related_name='field_values',
    )
    field_key = models.CharField('字段键', max_length=64)
    fiscal_year = models.ForeignKey(
        'fiscal.FiscalYear', verbose_name='财年', null=True, blank=True,
        on_delete=models.CASCADE, related_name='field_values',
    )
    value = models.JSONField('值', null=True, blank=True)
    version = models.BigIntegerField('版本（乐观锁）', default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '公司字段值'
        verbose_name_plural = '公司字段值'
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'field_key', 'fiscal_year'],
                name='uniq_company_field_year',
                nulls_distinct=False,
            ),
        ]
        indexes = [models.Index(fields=['company', 'field_key'])]
