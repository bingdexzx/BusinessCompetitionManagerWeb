"""区域字段定义（region-fields.json）的类型与构造函数。

区域字段是**比赛级**定义（所有区域共用），值按区域存；`region-fields.json` 格式：

    {
      "fields": [
        region_field("market_capacity", "市场容量", "NUMBER", default=100,
                     condition=region_condition("license", True)),
        region_field("level", "等级", "TEXT"),
      ]
    }

条件（可选）表示“合同修改该区域字段时的附加条件”：
- 默认 ``source=COMPANY``：引用公司实体字段；
- ``source=REGION``：引用目标区域的其他区域字段。
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

RegionFieldType = Literal['NUMBER', 'TEXT', 'BOOL', 'DATE']
ConditionOp = Literal['eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in']
ConditionSource = Literal['COMPANY', 'REGION']


class RegionCondition(TypedDict):
    """区域字段修改条件。"""

    fieldKey: str
    op: ConditionOp
    value: Any
    source: NotRequired[ConditionSource]


class RegionFieldSpec(TypedDict):
    """一个区域字段定义。"""

    key: str
    name: str
    type: RegionFieldType
    default: NotRequired[Any]
    condition: NotRequired[RegionCondition]


class RegionFieldsDocument(TypedDict):
    """region-fields.json 顶层结构。"""

    fields: list[RegionFieldSpec]


def region_condition(field_key: str, value: Any, op: ConditionOp = 'eq',
                     source: ConditionSource = 'COMPANY') -> RegionCondition:
    """构造修改条件：公司/区域字段 ``op`` ``value`` 时允许通过合同修改。"""
    return {'source': source, 'fieldKey': field_key, 'op': op, 'value': value}


def region_field(key: str, name: str, type: RegionFieldType = 'NUMBER', *,
                 default: Any = None,
                 condition: RegionCondition | None = None) -> RegionFieldSpec:
    """构造一个区域字段定义（type 只能是 NUMBER/TEXT/BOOL/DATE）。"""
    field: RegionFieldSpec = {'key': key, 'name': name, 'type': type}
    if default is not None:
        field['default'] = default
    if condition:
        field['condition'] = condition
    return field


def region_fields_document(fields: list[RegionFieldSpec]) -> RegionFieldsDocument:
    """把字段列表包成 region-fields.json 的顶层结构。"""
    return {'fields': fields}
