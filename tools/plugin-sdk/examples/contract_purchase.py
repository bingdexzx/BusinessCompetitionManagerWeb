"""示例：带清单与价格的采购合同（可直接复制到比赛包 plugins/ 下）。

编辑器提示：把 bcm_plugin_sdk 装进当前解释器后，`ctx.`、`Effect.`、构造函数都有补全。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcm_plugin_sdk import ContractContext, Effect

from bcm_plugin_sdk import (
    InputSchema,
    PartyRoles,
    list_field,
    list_sub_field,
    number_field,
    party_role,
)

CONTRACT_KEY = 'purchase_demo'
CONTRACT_NAME = '示例采购合同'
NUMBER_PREFIX = 'PD'

PARTY_ROLES: PartyRoles = [
    party_role('buyer', '买方'),
    party_role('seller', '卖方'),
    party_role('bank', '银行', optional=True),
]

INPUT_SCHEMA: InputSchema = [
    number_field('quantity', '数量', min=1),
    number_field('unitPrice', '单价', min=0),
    list_field(
        'materials', '原料清单', table='materials', item_label='原料', optional=True,
        fields=[list_sub_field('quantity', '数量', min=0)],
    ),
]


def check(ctx: ContractContext) -> list[str]:
    """前置检查：返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    total = ctx.input_number('quantity') * ctx.input_number('unitPrice')
    if ctx.company_field('buyer', 'cash', 0) < total:
        problems.append('买方资金不足')
    for row in ctx.input_list('materials'):
        name = str(row.get('item') or '')
        if name and ctx.item('materials', name) is None:
            problems.append(f'原料不存在：{name}')
    return problems


def apply(ctx: ContractContext) -> list[Effect]:
    """返回落账效果；不要直接改数据。"""
    total = ctx.input_number('quantity') * ctx.input_number('unitPrice')
    return [
        Effect.sub('buyer', 'cash', total),
        Effect.add('seller', 'cash', total),
    ]
