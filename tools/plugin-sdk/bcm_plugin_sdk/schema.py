"""插件结构体的 TypedDict（写 INPUT_SCHEMA / PARTY_ROLES 时提供键名补全）。"""

from __future__ import annotations

from typing import Literal

from typing import TypedDict


FieldType = Literal['NUMBER', 'TEXT', 'BOOLEAN', 'BOOL', 'LIST:materials', 'LIST:parts',
                    'LIST:products', 'LIST:map_nodes', 'LIST:cities', 'LIST:vehicles',
                    'LIST:companies', 'LIST:regions', 'LIST:fuels', 'LIST:tech_nodes',
                    'LIST:infrastructures', 'LIST:warehouses', 'LIST:production_lines',
                    'REF:companies', 'REF:regions', 'REF:cities', 'REF:map_nodes',
                    'REF:vehicles', 'REF:products', 'REF:parts', 'REF:materials',
                    'REF:fuels', 'REF:warehouses', 'REF:production_lines',
                    'REF:infrastructures', 'REF:tech_nodes']


class ListSubField(TypedDict, total=False):
    """清单行里的字段（例如 quantity）。"""

    key: str            # 行字段键，值写入 rows[i]['quantity']
    label: str          # 中文标签
    type: str           # 目前支持 'NUMBER'
    min: float          # 最小值（校验用）
    max: float          # 最大值（可选）


class InputField(TypedDict, total=False):
    """一个输入项。"""

    key: str            # 输入键；LIST 清单的键也用于 inputs[key]
    label: str          # 中文标签（界面显示）
    type: str           # NUMBER / TEXT / BOOLEAN / REF:<表> / LIST:<表>
    optional: bool      # 清单是否可选（仅 LIST 有意义）
    itemLabel: str      # 清单里「条目」的中文名（如「原料」）
    fields: list[ListSubField]   # 清单行字段；空列表 = 只登记条目
    min: float          # 数值类输入的最小值
    max: float          # 数值类输入的最大值
    options: list[str]  # 预留给枚举型（当前引擎未使用）


InputSchema = list[InputField]


class PartyRole(TypedDict, total=False):
    """参与方角色。"""

    role: str           # 角色键，Effect.company 可用它
    label: str          # 中文名（合同详情/确认按钮显示）
    optional: bool      # 是否可选参与方


PartyRoles = list[PartyRole]


class IndustryFieldSpec(TypedDict, total=False):
    """产业插件 FIELDS 的一项。"""

    key: str            # 字段键（插件 ctx 里用）
    name: str           # 中文名
    type: str           # NUMBER / TEXT / BOOL / REF / DATE
    table: str          # entity（实体信息表）/ finance（财务报表）
    formula: str        # 公式（存在即由引擎重算）
    default: object     # 初始值
    group: str          # 展示分组
    timerEnabled: bool  # 财年定时器
    timerTrigger: str   # FY_START / FY_END
