"""插件结构体 + 构造函数（写 INPUT_SCHEMA / PARTY_ROLES / FIELDS 时更省事）。

推荐写法：

    from bcm_plugin_sdk import (InputSchema, PartyRoles, InputField,
                                number_field, list_field, party_role)

    INPUT_SCHEMA: InputSchema = [
        number_field("quantity", "数量", min=1),
        list_field("materials", "原料清单", table="materials",
                   item_label="原料", fields=[number_field("quantity", "数量", min=1)]),
    ]
    PARTY_ROLES: PartyRoles = [party_role("buyer", "买方"), party_role("seller", "卖方")]

所有构造函数都会在**编辑器里校验参数名/类型**；运行时不依赖本包（这些常量只是普通 dict/list）。
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

# 与后端基础数据表一致
TableName = Literal[
    'materials', 'parts', 'products', 'map_nodes', 'cities', 'vehicles',
    'companies', 'regions', 'fuels', 'tech_nodes', 'infrastructures',
    'warehouses', 'production_lines',
]

FieldType = Literal[
    'NUMBER', 'TEXT', 'BOOLEAN', 'BOOL',
    'LIST:materials', 'LIST:parts', 'LIST:products', 'LIST:map_nodes',
    'LIST:cities', 'LIST:vehicles', 'LIST:companies', 'LIST:regions',
    'LIST:fuels', 'LIST:tech_nodes', 'LIST:infrastructures',
    'LIST:warehouses', 'LIST:production_lines',
    'REF:materials', 'REF:parts', 'REF:products', 'REF:map_nodes',
    'REF:cities', 'REF:vehicles', 'REF:companies', 'REF:regions',
    'REF:fuels', 'REF:tech_nodes', 'REF:infrastructures',
    'REF:warehouses', 'REF:production_lines',
]


class ListSubField(TypedDict):
    """清单行里的字段（目前只支持 NUMBER）。"""

    key: str
    label: str
    type: str
    min: NotRequired[float]
    max: NotRequired[float]


class InputField(TypedDict):
    """一个输入项。"""

    key: str
    label: str
    type: str
    optional: NotRequired[bool]
    itemLabel: NotRequired[str]
    fields: NotRequired[list[ListSubField]]
    min: NotRequired[float]
    max: NotRequired[float]
    options: NotRequired[list[str]]


InputSchema = list[InputField]


class PartyRole(TypedDict):
    """参与方角色。"""

    role: str
    label: str
    optional: NotRequired[bool]


PartyRoles = list[PartyRole]


class IndustryFieldSpec(TypedDict):
    """产业插件 FIELDS 的一项。"""

    key: str
    name: str
    type: str
    table: str
    default: NotRequired[Any]
    formula: NotRequired[str]
    group: NotRequired[str]
    timerEnabled: NotRequired[bool]
    timerTrigger: NotRequired[str]


# ---------------------------------------------------------------- 构造函数
def number_field(key: str, label: str, *, min: float | None = None,
                 max: float | None = None, optional: bool = False) -> InputField:
    """数值输入项（NUMBER）。"""
    field: InputField = {'key': key, 'label': label, 'type': 'NUMBER'}
    if min is not None:
        field['min'] = min
    if max is not None:
        field['max'] = max
    if optional:
        field['optional'] = True
    return field


def text_field(key: str, label: str, *, optional: bool = False) -> InputField:
    """文本输入项（TEXT）。"""
    field: InputField = {'key': key, 'label': label, 'type': 'TEXT'}
    if optional:
        field['optional'] = True
    return field


def bool_field(key: str, label: str, *, optional: bool = False) -> InputField:
    """开关输入项（BOOLEAN）。"""
    field: InputField = {'key': key, 'label': label, 'type': 'BOOLEAN'}
    if optional:
        field['optional'] = True
    return field


def ref_field(key: str, label: str, table: TableName, *, optional: bool = False) -> InputField:
    """可搜索下拉（REF:<表>）：值是条目名称字符串。"""
    field: InputField = {'key': key, 'label': label, 'type': f'REF:{table}'}
    if optional:
        field['optional'] = True
    return field


def list_sub_field(key: str, label: str, *, min: float | None = 0,
                   max: float | None = None) -> ListSubField:
    """清单行内的数量字段。"""
    sub: ListSubField = {'key': key, 'label': label, 'type': 'NUMBER'}
    if min is not None:
        sub['min'] = min
    if max is not None:
        sub['max'] = max
    return sub


def list_field(key: str, label: str, table: TableName, item_label: str, *,
               fields: list[ListSubField] | None = None,
               optional: bool = False) -> InputField:
    """清单（LIST:<表>）：fields=[] 表示只登记条目、不填数量。"""
    field: InputField = {
        'key': key, 'label': label, 'type': f'LIST:{table}', 'itemLabel': item_label,
    }
    if fields:
        field['fields'] = fields
    if optional:
        field['optional'] = True
    return field


def party_role(role: str, label: str, *, optional: bool = False) -> PartyRole:
    """参与方角色；role 会作为 ctx.party(role) / Effect(company=role) 的键。"""
    item: PartyRole = {'role': role, 'label': label}
    if optional:
        item['optional'] = True
    return item


def industry_field(key: str, name: str, *, type: str = 'NUMBER',
                   table: Literal['entity', 'finance'] = 'entity',
                   default: Any = None, formula: str = '', group: str = '',
                   timer_enabled: bool = False,
                   timer_trigger: Literal['FY_START', 'FY_END'] = 'FY_START') -> IndustryFieldSpec:
    """产业字段（写 FIELDS 用）；formula 非空时由引擎重算。"""
    field: IndustryFieldSpec = {'key': key, 'name': name, 'type': type, 'table': table}
    if default is not None:
        field['default'] = default
    if formula:
        field['formula'] = formula
    if group:
        field['group'] = group
    if timer_enabled:
        field['timerEnabled'] = True
        field['timerTrigger'] = timer_trigger
    return field
