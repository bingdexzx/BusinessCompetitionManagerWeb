"""产业类型插件模板（带类型提示：IDE 里写 ctx. 会有补全与参数说明）。

复制到 media/plugins/<key>/<version>/industry_<key>.py 后修改。
运行时由引擎注入 ctx，模板里的 bcm_plugin_sdk 导入只用于编辑器类型检查。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅编辑器/静态检查生效
    from bcm_plugin_sdk import IndustryContext, IndustryFieldSpec

INDUSTRY_KEY = 'my_industry'
INDUSTRY_NAME = '我的产业'

# 字段定义：table=entity（实体信息表）/ finance（财务报表）
# 带 formula 的字段由引擎按公式重算（不要手写 is_calculated）
FIELDS: list[IndustryFieldSpec] = [
    {
        'key': '产能', 'name': '产能', 'type': 'NUMBER', 'table': 'entity',
        'default': 0, 'group': '经营',
    },
    {
        'key': '现金', 'name': '现金', 'type': 'NUMBER', 'table': 'finance',
        'default': 0, 'group': '财务',
    },
    {
        # 公式示例：总资产 = 现金 + 库存估值（引擎白名单函数：IF/round/min/max/abs/sqrt/pow/log/ln）
        'key': '总资产', 'name': '总资产', 'type': 'NUMBER', 'table': 'finance',
        'formula': '现金 + 0', 'group': '财务',
    },
]


def timer_check(ctx: IndustryContext) -> list[str]:
    """财年定时器检查（可选）：返回问题列表（空 = 通过）。

    可用 ctx 方法：
      ctx.company_field(公司, 字段) / ctx.company_industry(公司)
      ctx.item(表, 名称) / ctx.items(表) / ctx.item_names(表)
      ctx.price(原料, 区域) / ctx.prices(原料) / ctx.price_names()
      ctx.node_region(节点) / ctx.node_city(节点) / ctx.node_regions() / ctx.node_cities()
      ctx.basedata(表) / ctx.number(值)
    """
    problems: list[str] = []
    return problems
