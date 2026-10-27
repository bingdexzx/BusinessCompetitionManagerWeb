"""基础数据模型（照旧项目字段结构重写：表名/字段名/choices/Decimal(60,4)/约束逐项照搬）。

多库适配（§5.2，与 stock 同口径）：不建跨库外键——旧的 competition 外键整体去掉（一个比赛一个库，
归属由库决定），指向公司/用户一律 BigIntegerField 存 ID；本 app 内部关联照旧用外键；主表保留
created_at/updated_at 并按旧表名建 idx_<table>_updated 索引（delta 同步按 updated_at keyset 拉取）。
"""

from django.db import models


class Fuel(models.Model):
    name = models.CharField('名称', max_length=255)
    # 燃料单价：玩家购买时累加到现金支出，浮点累计会漂。改 Decimal（旧口径）。
    price_per_liter = models.DecimalField(
        '燃料单价', max_digits=60, decimal_places=4,
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '燃料'
        verbose_name_plural = '燃料'
        db_table = 'fuels'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_fuels_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_fuels_updated'),
        ]

    def __str__(self):
        return self.name


class Warehouse(models.Model):
    TYPE_CHOICES = [
        ("MATERIAL", "MATERIAL"),
        ("PART", "PART"),
        ("PRODUCT", "PRODUCT"),
        ("FUEL", "FUEL"),
    ]

    name = models.CharField('名称', max_length=255)
    # 容量 + 价格：玩家购买场景，必须 Decimal（旧口径）。
    capacity = models.DecimalField('容量', max_digits=60, decimal_places=4)
    price = models.DecimalField('价格', max_digits=60, decimal_places=4)
    type = models.CharField('仓库类型', max_length=16, choices=TYPE_CHOICES)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '仓库'
        verbose_name_plural = '仓库'
        db_table = 'warehouses'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_warehouses_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_warehouses_updated'),
        ]

    def __str__(self):
        return self.name


class Vehicle(models.Model):
    """载具主数据。fuel 用 PROTECT：被引用的燃料不允许直接删除（旧口径）。"""

    name = models.CharField('名称', max_length=128)
    fuel = models.ForeignKey(
        Fuel,
        verbose_name='燃料',
        on_delete=models.PROTECT,
        related_name='vehicles',
    )
    # 油耗/载货：均为比率/容量配置，可保留 Float（旧口径）
    fuel_consumption_per_km = models.FloatField('每公里油耗')
    # 原 max_cargo 拆分为三类载货量（旧 D16）：原料、零件、产品各限独立上限。
    max_material_cargo = models.FloatField('原料载货上限', default=0)
    max_part_cargo = models.FloatField('零件载货上限', default=0)
    max_product_cargo = models.FloatField('产品载货上限', default=0)
    # 价格：玩家购买场景，必须 Decimal
    price = models.DecimalField('价格', max_digits=60, decimal_places=4)
    # 碳排：派生系数，Float 足够
    carbon_emission = models.FloatField('碳排系数')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '载具'
        verbose_name_plural = '载具'
        db_table = 'vehicles'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_vehicles_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_vehicles_updated'),
        ]

    def __str__(self):
        return self.name


class MapNodeType(models.Model):
    name = models.CharField('名称', max_length=128)
    description = models.TextField('描述', null=True, blank=True)
    color = models.CharField('颜色', max_length=32, null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '地图节点类型'
        verbose_name_plural = '地图节点类型'
        db_table = 'map_node_types'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_map_node_types_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_map_node_types_updated'),
        ]

    def __str__(self):
        return self.name


class PathType(models.Model):
    name = models.CharField('名称', max_length=128)
    description = models.TextField('描述', null=True, blank=True)
    color = models.CharField('颜色', max_length=32, null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '路径类型'
        verbose_name_plural = '路径类型'
        db_table = 'path_types'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_path_types_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_path_types_updated'),
        ]

    def __str__(self):
        return self.name


class MapNode(models.Model):
    name = models.CharField('名称', max_length=128)
    region = models.CharField('所属区域', max_length=128, default="")
    node_type = models.ForeignKey(
        MapNodeType,
        verbose_name='节点类型',
        on_delete=models.CASCADE,
        related_name='nodes',
    )
    x = models.FloatField('横坐标', default=0)
    y = models.FloatField('纵坐标', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '地图节点'
        verbose_name_plural = '地图节点'
        db_table = 'map_nodes'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_map_nodes_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_map_nodes_updated'),
        ]

    def __str__(self):
        return self.name


class MapEdge(models.Model):
    """地图边（db_table=map_edges）：起终点唯一。"""

    from_node = models.ForeignKey(
        MapNode,
        verbose_name='起点节点',
        on_delete=models.CASCADE,
        related_name='edges_from',
    )
    to_node = models.ForeignKey(
        MapNode,
        verbose_name='终点节点',
        on_delete=models.CASCADE,
        related_name='edges_to',
    )
    distance = models.FloatField('距离', default=0)
    path_type = models.ForeignKey(
        PathType,
        verbose_name='路径类型',
        on_delete=models.CASCADE,
        related_name='edges',
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '地图边'
        verbose_name_plural = '地图边'
        db_table = 'map_edges'
        constraints = [
            models.UniqueConstraint(
                fields=['from_node', 'to_node'], name='uniq_map_edges_from_to',
            ),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_map_edges_updated'),
        ]

    def __str__(self):
        return f"边#{self.id}"


class Material(models.Model):
    TYPE_CHOICES = [("NORMAL", "NORMAL"), ("SPECIAL", "SPECIAL")]

    name = models.CharField('名称', max_length=255)
    origin = models.CharField('产地', max_length=255)
    carbon_emission_coefficient = models.FloatField('碳排系数')
    # 按地点（地图节点）价格：JSON 字符串 { [mapNodeId]: 价格 }（旧口径 TextField）
    node_prices = models.TextField('按地点价格', default="{}")
    type = models.CharField('原料类型', max_length=16, default="NORMAL", choices=TYPE_CHOICES)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '原料'
        verbose_name_plural = '原料'
        db_table = 'materials'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_materials_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_materials_updated'),
        ]

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField('名称', max_length=128)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '产品'
        verbose_name_plural = '产品'
        db_table = 'products'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_products_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_products_updated'),
        ]

    def __str__(self):
        return self.name


class ProductPart(models.Model):
    """产品-零件配比（db_table=product_parts）。product / part 任一删除均级联删除本关联行。"""

    product = models.ForeignKey(
        Product,
        verbose_name='产品',
        on_delete=models.CASCADE,
        related_name='product_parts',
    )
    part = models.ForeignKey(
        'Part',
        verbose_name='零件',
        on_delete=models.CASCADE,
        related_name='product_parts',
    )
    ratio = models.FloatField('配比')

    class Meta:
        verbose_name = '产品零件配比'
        verbose_name_plural = '产品零件配比'
        db_table = 'product_parts'
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'part'], name='uniq_product_parts_product_part',
            ),
        ]

    def __str__(self):
        return f"{self.product_id}-{self.part_id}"


class ProductTechRequirement(models.Model):
    product = models.ForeignKey(
        Product,
        verbose_name='产品',
        on_delete=models.CASCADE,
        related_name='tech_requirements',
    )
    tech_node = models.ForeignKey(
        'TechNode',
        verbose_name='科技节点',
        on_delete=models.CASCADE,
        related_name='product_requirements',
    )

    class Meta:
        verbose_name = '产品科技需求'
        verbose_name_plural = '产品科技需求'
        db_table = 'product_tech_requirements'
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'tech_node'], name='uniq_product_tech_requirements',
            ),
        ]

    def __str__(self):
        return f"{self.product_id}-{self.tech_node_id}"


class Part(models.Model):
    name = models.CharField('名称', max_length=128)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '零件'
        verbose_name_plural = '零件'
        db_table = 'parts'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_parts_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_parts_updated'),
        ]

    def __str__(self):
        return self.name


class PartMaterial(models.Model):
    """零件-原料配比（db_table=part_materials）。part / material 任一删除均级联删除本关联行。"""

    part = models.ForeignKey(
        Part,
        verbose_name='零件',
        on_delete=models.CASCADE,
        related_name='part_materials',
    )
    material = models.ForeignKey(
        Material,
        verbose_name='原料',
        on_delete=models.CASCADE,
        related_name='part_materials',
    )
    ratio = models.FloatField('配比')

    class Meta:
        verbose_name = '零件原料配比'
        verbose_name_plural = '零件原料配比'
        db_table = 'part_materials'
        constraints = [
            models.UniqueConstraint(
                fields=['part', 'material'], name='uniq_part_materials_part_material',
            ),
        ]

    def __str__(self):
        return f"{self.part_id}-{self.material_id}"


class PartTechRequirement(models.Model):
    part = models.ForeignKey(
        Part,
        verbose_name='零件',
        on_delete=models.CASCADE,
        related_name='tech_requirements',
    )
    tech_node = models.ForeignKey(
        'TechNode',
        verbose_name='科技节点',
        on_delete=models.CASCADE,
        related_name='part_requirements',
    )

    class Meta:
        verbose_name = '零件科技需求'
        verbose_name_plural = '零件科技需求'
        db_table = 'part_tech_requirements'
        constraints = [
            models.UniqueConstraint(
                fields=['part', 'tech_node'], name='uniq_part_tech_requirements',
            ),
        ]

    def __str__(self):
        return f"{self.part_id}-{self.tech_node_id}"


class Infrastructure(models.Model):
    name = models.CharField('名称', max_length=255)
    # footprint 是面积（可保留 Float：图形属性，非账目）
    footprint = models.FloatField('占地面积')
    # bonus 系列：百分比系数（0.05=+5%），用 Float 保留（区间运算，精度足）
    employment_rate_bonus = models.FloatField('就业率加成', default=0)
    population_bonus = models.FloatField('人口加成', default=0)
    high_quality_population_bonus = models.FloatField('高质量人口加成', default=0)
    # 价格类：必须 Decimal（玩家购买场景）
    price = models.DecimalField('价格', max_digits=60, decimal_places=4)
    happiness_index_bonus = models.FloatField('幸福指数加成', default=0)
    per_capita_income_bonus = models.FloatField('人均收入加成', default=0)
    carbon_reduction_bonus = models.FloatField('碳减加成', default=0)
    activation_price = models.DecimalField('激活价格', max_digits=60, decimal_places=4)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '基建'
        verbose_name_plural = '基建'
        db_table = 'infrastructures'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_infrastructures_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_infrastructures_updated'),
        ]

    def __str__(self):
        return self.name


class TechNode(models.Model):
    name = models.CharField('名称', max_length=128)
    description = models.TextField('描述', null=True, blank=True)
    tier = models.IntegerField('层级', default=0)
    research_cost = models.FloatField('研发成本', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '科技节点'
        verbose_name_plural = '科技节点'
        db_table = 'tech_nodes'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_tech_nodes_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_tech_nodes_updated'),
        ]

    def __str__(self):
        return self.name


class TechPrerequisite(models.Model):
    """科技节点的前置依赖关系（自关联中间表）：node 为配置方，prerequisite 为本节点依赖的前置科技。"""

    node = models.ForeignKey(
        TechNode,
        verbose_name='科技节点',
        on_delete=models.CASCADE,
        related_name='prerequisites',
    )
    prerequisite = models.ForeignKey(
        TechNode,
        verbose_name='前置科技',
        on_delete=models.CASCADE,
        related_name='required_by',
    )

    class Meta:
        verbose_name = '科技前置依赖'
        verbose_name_plural = '科技前置依赖'
        db_table = 'tech_prerequisites'
        constraints = [
            models.UniqueConstraint(
                fields=['node', 'prerequisite'], name='uniq_tech_prerequisites_node_pre',
            ),
        ]

    def __str__(self):
        return f"{self.node_id}-{self.prerequisite_id}"


class ProductionLine(models.Model):
    name = models.CharField('名称', max_length=255)
    # 价格 + 年产能：玩家购买场景，必须 Decimal（旧口径）。
    price = models.DecimalField('价格', max_digits=60, decimal_places=4)
    labor_count = models.IntegerField('用工数')
    max_per_year = models.DecimalField('年产能上限', max_digits=60, decimal_places=4)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '生产线'
        verbose_name_plural = '生产线'
        db_table = 'production_lines'
        constraints = [
            models.UniqueConstraint(fields=['name'], name='uniq_production_lines_name'),
        ]
        indexes = [
            models.Index(fields=['updated_at'], name='idx_production_lines_updated'),
        ]

    def __str__(self):
        return self.name


class VehiclePathType(models.Model):
    """载具-路径类型关联：任一外键删除均级联删除本行；沿用旧约定自增 id 主键 + 复合唯一约束。"""

    vehicle = models.ForeignKey(
        Vehicle,
        verbose_name='载具',
        on_delete=models.CASCADE,
        related_name='vehicle_path_types',
    )
    path_type = models.ForeignKey(
        PathType,
        verbose_name='路径类型',
        on_delete=models.CASCADE,
        related_name='vehicles',
    )

    class Meta:
        verbose_name = '载具路径类型'
        verbose_name_plural = '载具路径类型'
        db_table = 'vehicle_path_types'
        constraints = [
            models.UniqueConstraint(
                fields=['vehicle', 'path_type'], name='uniq_vehicle_path_types',
            ),
        ]

    def __str__(self):
        return f"{self.vehicle_id}-{self.path_type_id}"
