"""合同类型插件模板（带类型提示：IDE 里写 ctx. 会有补全与参数说明）。

复制到 media/plugins/<key>/<version>/contract_<key>.py 后修改。
运行时由引擎注入 ctx / Effect，模板里的 bcm_plugin_sdk 导入只用于编辑器类型检查。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅编辑器/静态检查生效，运行时不会 import（引擎已注入同名对象）
    from bcm_plugin_sdk import ContractContext, Effect, InputSchema, PartyRoles

CONTRACT_KEY = 'my_contract'
CONTRACT_NAME = '我的合同'

# 参与方：role 会作为 ctx.party(role) / Effect(company=role) 的键
PARTY_ROLES: PartyRoles = [
    {'role': '买方', 'label': '买方'},
    {'role': '卖方', 'label': '卖方'},
]

# 输入项：type 决定界面控件
#   NUMBER / TEXT / BOOLEAN
#   REF:<表>   可搜索下拉（存条目名称）
#   LIST:<表>  清单（多行；fields 决定行内字段，fields=[] 表示只登记条目）
INPUT_SCHEMA: InputSchema = [
    {'key': '数量', 'label': '数量', 'type': 'NUMBER', 'min': 1},
    {
        'key': '原料清单', 'label': '原料清单', 'type': 'LIST:materials',
        'itemLabel': '原料', 'optional': True,
        'fields': [{'key': 'quantity', 'label': '数量', 'type': 'NUMBER', 'min': 1}],
    },
]


def check(ctx: ContractContext) -> list[str]:
    """前置检查：返回问题列表（空 = 通过）。

    可用（IDE 有补全与说明）：
      ctx.input / input_number / input_text / input_bool / input_list
      ctx.party / company_field / company_industry
      ctx.item(表, 名称) / items / item_names
      ctx.price(原料, 区域) / prices / price_names
      ctx.node_region(节点) / node_city(节点) / node_regions / node_cities
    """
    problems: list[str] = []
    quantity = ctx.input_number('数量')
    if quantity <= 0:
        problems.append('数量必须大于 0')
    for row in ctx.input_list('原料清单'):
        # ctx.item 返回该条目的全部字段（价格/容量/配比/坐标…），查不到返回 None
        if ctx.item('materials', row.get('item', '')) is None:
            problems.append(f'原料不存在：{row.get("item", "")}')
    return problems


def apply(ctx: ContractContext) -> list[Effect]:
    """落账：返回 Effect 列表（不要直接改数据）。

    - ``Effect.add(company, field, value)``：加
    - ``Effect.sub(company, field, value)``：减
    - ``Effect.set(company, field, value)``：覆盖
    - ``company`` 可写参与方角色（'买方'）或公司名；``region=`` 非空表示区域字段效果
    """
    quantity = ctx.input_number('数量')
    amount = quantity * 100  # 示例单价；真实插件可用 ctx.item / ctx.price 取价
    return [
        Effect.sub('买方', 'yinhangzhanghu', amount),
        Effect.add('卖方', 'yinhangzhanghu', amount),
    ]
