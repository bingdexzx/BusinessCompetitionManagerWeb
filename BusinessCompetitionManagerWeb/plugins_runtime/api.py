"""插件可见的受控 API（§8：插件只拿 ctx，不暴露 Django ORM）。"""

from dataclasses import dataclass
from typing import Any

from plugins_runtime import ops


@dataclass(frozen=True)
class Effect:
    """落账效果（§7.2）：``Effect(company, field, op, value, region='')``。

    - ``company``：参与方角色（``'买方'``）或公司名；两者都匹配不到时，执行阶段报
      「效果指向未知公司/角色」；
    - ``field``：公司字段键（产业插件里定义的 key），区域字段时为区域字段键；
    - ``op``：``ADD``（加）/ ``SUB``（减）/ ``SET``（覆盖），可直接写字符串，也可用
      ``Effect.ADD`` / ``Effect.SUB`` / ``Effect.SET`` 常量；
    - ``value``：数值（ADD/SUB）或任意字段值（SET）；
    - ``region``：非空表示**区域字段**效果：``company`` 是发起该效果的公司
      （用于校验区域字段的修改条件），``field`` 是区域字段键，``region`` 是区域名或 ID。

    简写构造（推荐）：``Effect.add(...)`` / ``Effect.sub(...)`` / ``Effect.set(...)``，
    与 ``Effect(..., op='ADD')`` 完全等价。
    """

    ADD = ops.ADD
    SUB = ops.SUB
    SET = ops.SET

    company: str
    field: str
    op: str
    value: Any
    region: str = ''

    def __post_init__(self):
        if not ops.is_valid(self.op):
            raise ValueError(f'非法效果操作：{self.op}')

    @classmethod
    def add(cls, company, field, value, region=''):
        """``ADD`` 效果：在现有值上加 ``value``（非数值按 0 计）。"""
        return cls(company=company, field=field, op=ops.ADD, value=value, region=region)

    @classmethod
    def sub(cls, company, field, value, region=''):
        """``SUB`` 效果：在现有值上减 ``value``（非数值按 0 计）。"""
        return cls(company=company, field=field, op=ops.SUB, value=value, region=region)

    @classmethod
    def set(cls, company, field, value, region=''):
        """``SET`` 效果：直接覆盖为 ``value``（回滚 = 恢复落账前快照）。"""
        return cls(company=company, field=field, op=ops.SET, value=value, region=region)


class ContractContext:
    """合同插件执行上下文（M1 定义接口，M3 满实现数据读写）。"""

    def __init__(self, parties=None, inputs=None, fields=None, basedata=None,
                 industries=None, node_regions=None, node_cities=None,
                 material_prices=None, item_detail_provider=None):
        self._parties = parties or {}
        self._inputs = inputs or {}
        self._fields = fields or {}
        self._basedata = basedata or {}
        self._industries = industries or {}
        # 地图节点（城市）→ 所属区域名；合同插件用它把导入的城市数据换成区域字段的 region
        self._node_regions = node_regions or {}
        # 地图节点（车站/机场/码头/矿点…）→ 所属城市
        self._node_cities = node_cities or {}
        # 原料 → {区域: 参考价}；来自原料表「按地点价格」按区域归并（合同插件查价用）
        self._material_prices = material_prices or {}
        # 基础数据条目的数值：table -> {名称: {字段: 值}}（价格/容量/用工数/前置科技…）
        self._item_detail_provider = item_detail_provider
        self._item_detail_cache = {}

    def party(self, role: str) -> str:
        return self._parties.get(role)

    def company_field(self, role: str, field: str, default=0):
        return self._fields.get((role, field), default)

    def company_industry(self, role: str):
        """参与方公司所属产业 key（公司未设置产业时返回 None）。"""
        return self._industries.get(role)

    def input(self, key: str, default=None):
        """原样返回输入值（可能是 str / int / float / bool / dict，取决于录入方式）。"""
        return self._inputs.get(key, default)

    def input_list(self, key: str) -> list:
        """清单类输入（如原料清单）→ ``[{'item': '铁', 'quantity': 10}, ...]``。

        每行原样返回（数值可能仍是字符串），用 ``float(row['quantity'])`` 或
        ``ctx.number(row.get('quantity'))`` 归一。
        """
        value = self._inputs.get(key)
        if not isinstance(value, list):
            return []
        return [dict(row) if isinstance(row, dict) else {'item': row} for row in value]

    @staticmethod
    def number(value, default: float = 0.0) -> float:
        """把任意输入值转成数字（清单行的数量也适用）。"""
        if isinstance(value, bool):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def input_number(self, key: str, default: float = 0.0) -> float:
        """输入项按数值读取：字符串、空值、非法值都安全转成 float（失败返回 default）。"""
        value = self._inputs.get(key)
        if isinstance(value, bool):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def input_text(self, key: str, default: str = '') -> str:
        """输入项按文本读取（None → default，去首尾空格）。"""
        value = self._inputs.get(key)
        if value is None:
            return default
        return str(value).strip() or default

    def input_bool(self, key: str, default: bool = False) -> bool:
        """输入项按布尔读取：接受 true/false、1/0、是/否。"""
        value = self._inputs.get(key)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in ('true', '1', 'yes', 'y', '是'):
            return True
        if text in ('false', '0', 'no', 'n', '否'):
            return False
        return default

    def basedata(self, table: str, code: str):
        return self._basedata.get((table, code))

    # ------------------------------------------------------------ 地图节点
    def node_region(self, node, default: str = ''):
        """地图节点（名称或 ID）→ 所属区域名；查不到返回 ``default``。"""
        key = self._node_key(node)
        if key is None:
            return default
        return self._node_regions.get(key, default) or default

    def node_city(self, node, default: str = ''):
        """地图节点（名称或 ID）→ 所属城市名；查不到返回 ``default``。"""
        key = self._node_key(node)
        if key is None:
            return default
        return self._node_cities.get(key, default) or default

    def node_regions(self) -> dict:
        """节点名 → 区域名 的只读副本（便于批量处理）。"""
        return {
            key: value for key, value in self._node_regions.items()
            if not str(key).startswith('#')
        }

    def node_cities(self) -> dict:
        """节点名 → 城市名 的只读副本。"""
        return {
            key: value for key, value in self._node_cities.items()
            if not str(key).startswith('#')
        }

    @staticmethod
    def _node_key(node):
        """节点引用归一：``12`` / ``'12'`` → ``'#12'``；``'松平'`` → ``'松平'``。"""
        if node is None or node == '':
            return None
        text = str(node).strip()
        if not text:
            return None
        if text.startswith('#'):
            return text
        if text.isdigit():
            return f'#{text}'
        return text

    # ------------------------------------------------------------ 原料价格
    def price(self, material, region='', default=None):
        """原料参考价（来自原料表「按地点价格」，同区域多城市取均价）。

        - 给了 ``region``：只认该区域的价格，查不到返回 ``default``；
        - 不给 ``region``：返回各地区价格的算术平均（全国参考价），没数据返回 ``default``。
        """
        prices = self._material_prices.get(str(material or '').strip()) or {}
        region = str(region or '').strip()
        if region:
            return prices.get(region, default)
        if not prices:
            return default
        return round(sum(prices.values()) / len(prices), 4)

    def prices(self, material) -> dict:
        """原料名 → {区域: 参考价}（只读副本；没有价格时返回空字典）。"""
        return dict(self._material_prices.get(str(material or '').strip(), {}))

    def price_names(self) -> list:
        """有参考价的原料名（排序）。"""
        return sorted(self._material_prices)

    # ------------------------------------------------------------ 基础数据条目
    def items(self, table) -> dict:
        """某张基础数据表 → {名称: {字段: 值}}（只读副本，按表缓存；取不到返回空字典）。

        字段含义见 :meth:`item`。
        """
        table = str(table or '').strip().lower()
        if not table or self._item_detail_provider is None:
            return {}
        if table not in self._item_detail_cache:
            try:
                self._item_detail_cache[table] = dict(self._item_detail_provider(table) or {})
            except Exception:  # noqa: BLE001 —— 取不到明细不影响合同本体
                self._item_detail_cache[table] = {}
        return {name: dict(value) for name, value in self._item_detail_cache[table].items()}

    def item(self, table, name, default=None):
        """按「基础数据表 + 条目名」返回该条目的全部数值（字典）；查不到返回 ``default``。

        表与典型返回：
        ``materials`` 产地/碳排/按地点价格；``parts`` 原料配比；``products`` 零件配比；
        ``map_nodes`` / ``cities`` 区域/城市/坐标；``fuels`` 燃料单价；
        ``tech_nodes`` 描述/研发成本/前置科技；``infrastructures`` 面积/价格/加成；
        ``warehouses`` 容量/价格/类型；``production_lines`` 价格/用工数/年产能；
        ``vehicles`` 载具全部字段；``companies`` 产业 key。
        """
        table = str(table or '').strip().lower()
        name = str(name or '').strip()
        if not table or not name:
            return default
        data = self.items(table).get(name)
        return default if data is None else data

    def item_names(self, table) -> list:
        """某张基础数据表的全部条目名（排序；取不到返回空列表）。"""
        return sorted(self.items(table) or {})

    # ------------------------------------------------------------ 旧名别名（已弃用）
    # 只做转发，保证老插件不用改；新插件请用上面的短名。
    def region_of(self, node_name, default: str = ''):
        """已弃用：用 ``ctx.node_region(节点)``。"""
        return self.node_region(node_name, default)

    def region_of_node(self, node_id, default: str = ''):
        """已弃用：用 ``ctx.node_region(节点ID)``。"""
        return self.node_region(node_id, default)

    def city_of(self, node_name, default: str = ''):
        """已弃用：用 ``ctx.node_city(节点)``。"""
        return self.node_city(node_name, default)

    def city_of_node(self, node_id, default: str = ''):
        """已弃用：用 ``ctx.node_city(节点ID)``。"""
        return self.node_city(node_id, default)

    def node_region_map(self) -> dict:
        """已弃用：用 ``ctx.node_regions()``。"""
        return self.node_regions()

    def node_city_map(self) -> dict:
        """已弃用：用 ``ctx.node_cities()``。"""
        return self.node_cities()

    def material_price(self, material, region='', default=None):
        """已弃用：用 ``ctx.price(原料, 区域)``。"""
        return self.price(material, region, default)

    def material_price_map(self, material) -> dict:
        """已弃用：用 ``ctx.prices(原料)``。"""
        return self.prices(material)

    def material_names(self) -> list:
        """已弃用：用 ``ctx.price_names()``。"""
        return self.price_names()

    def item_details(self, table) -> dict:
        """已弃用：用 ``ctx.items(表)``。"""
        return self.items(table)

    def item_detail(self, table, name, default=None):
        """已弃用：用 ``ctx.item(表, 名称)``。"""
        return self.item(table, name, default)


class IndustryContext:
    """产业插件上下文（M1 定义接口）。"""

    def __init__(self, fields=None):
        self._fields = fields or {}

    def field(self, key: str, default=None):
        return self._fields.get(key, default)
