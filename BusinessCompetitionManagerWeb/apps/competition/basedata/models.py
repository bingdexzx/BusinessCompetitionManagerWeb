"""基础数据 10 类（§6.2 basedata_*、《比赛包格式规范》§5）。

由比赛包表格导入到各比赛库；**扩展列**原样保留在 ``meta`` JSON（不丢数据）。
"""

from django.db import models


class BaseDataRow(models.Model):
    """基础数据公共行：code 唯一 + 名称 + 备注 + 扩展列。"""

    code = models.CharField('编码', max_length=64, unique=True)
    name = models.CharField('名称', max_length=120)
    notes = models.TextField('备注', blank=True)
    meta = models.JSONField('扩展列', default=dict, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f'{self.code} {self.name}'


class Fuel(BaseDataRow):
    """燃料"""

    unit = models.CharField('单位', max_length=32, blank=True)
    energy_value = models.FloatField('热值', null=True, blank=True)
    price = models.FloatField('单价', null=True, blank=True)

    class Meta:
        verbose_name = '燃料'
        verbose_name_plural = '燃料'


class Warehouse(BaseDataRow):
    """仓库"""

    capacity = models.FloatField('容量', null=True, blank=True)
    region_code = models.CharField('所在地区(REF:maps)', max_length=64, blank=True)

    class Meta:
        verbose_name = '仓库'
        verbose_name_plural = '仓库'


class Vehicle(BaseDataRow):
    """载具"""

    vehicle_type = models.CharField('载具类型', max_length=64, blank=True)
    load_capacity = models.FloatField('载重', null=True, blank=True)
    speed = models.FloatField('速度', null=True, blank=True)
    fuel_code = models.CharField('燃料(REF:fuels)', max_length=64, blank=True)
    fuel_consumption = models.FloatField('油耗', null=True, blank=True)

    class Meta:
        verbose_name = '载具'
        verbose_name_plural = '载具'


class MapRegion(BaseDataRow):
    """地图（地区）"""

    region_type = models.CharField('地区类型', max_length=64, blank=True)
    adjacent_codes = models.CharField('相邻地区', max_length=500, blank=True)  # 逗号分隔 code
    distance = models.FloatField('距离', null=True, blank=True)

    class Meta:
        verbose_name = '地图'
        verbose_name_plural = '地图'


class Material(BaseDataRow):
    """原料"""

    unit = models.CharField('单位', max_length=32, blank=True)
    base_price = models.FloatField('基础价格', null=True, blank=True)

    class Meta:
        verbose_name = '原料'
        verbose_name_plural = '原料'


class Product(BaseDataRow):
    """产品"""

    unit = models.CharField('单位', max_length=32, blank=True)
    base_price = models.FloatField('基础价格', null=True, blank=True)

    class Meta:
        verbose_name = '产品'
        verbose_name_plural = '产品'


class Part(BaseDataRow):
    """零件"""

    unit = models.CharField('单位', max_length=32, blank=True)
    base_price = models.FloatField('基础价格', null=True, blank=True)
    compatible_types = models.CharField('适配类型', max_length=500, blank=True)  # 逗号分隔

    class Meta:
        verbose_name = '零件'
        verbose_name_plural = '零件'


class Infrastructure(BaseDataRow):
    """基建"""

    infra_type = models.CharField('基建类型', max_length=64, blank=True)
    build_cost = models.FloatField('建造成本', null=True, blank=True)
    maintenance_cost = models.FloatField('维护成本', null=True, blank=True)
    effect = models.JSONField('效果', default=dict, blank=True)

    class Meta:
        verbose_name = '基建'
        verbose_name_plural = '基建'


class TechNode(BaseDataRow):
    """科技树"""

    tier = models.PositiveSmallIntegerField('层级', null=True, blank=True)
    prerequisite_codes = models.CharField('前置科技', max_length=500, blank=True)  # 逗号分隔
    research_cost = models.FloatField('研发成本', null=True, blank=True)
    effect = models.JSONField('效果', default=dict, blank=True)

    class Meta:
        verbose_name = '科技树'
        verbose_name_plural = '科技树'


class ProductionLine(BaseDataRow):
    """生产线"""

    inputs = models.JSONField('投入', default=dict, blank=True)   # {"<物料code>": 数量}
    outputs = models.JSONField('产出', default=dict, blank=True)  # {"<产品code>": 数量}
    capacity = models.FloatField('产能', null=True, blank=True)
    build_cost = models.FloatField('建造成本', null=True, blank=True)

    class Meta:
        verbose_name = '生产线'
        verbose_name_plural = '生产线'
