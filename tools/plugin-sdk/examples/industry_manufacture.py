"""示例：产业插件（字段 + 公式 + 财年定时器）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bcm_plugin_sdk import IndustryContext

from bcm_plugin_sdk import IndustryFieldSpec, industry_field

INDUSTRY_KEY = 'manufacture_demo'
INDUSTRY_NAME = '示例制造业'

FIELDS: list[IndustryFieldSpec] = [
    industry_field('cash', '现金', table='finance', default=100000, group='财务'),
    industry_field('capacity', '产能', table='entity', default=10, group='经营'),
    industry_field('loan_limit', '贷款额度', table='finance',
                   formula='cash * 0.5', group='财务'),
    industry_field('labor_used', '本财年已配置劳动力', table='entity', default=0,
                   timer_enabled=True, timer_trigger='FY_START'),
]


def timer_check(ctx: IndustryContext) -> list[str]:
    """财年定时器检查（可选）：返回问题列表。"""
    if ctx.company_field('', 'capacity', 0) < 0:
        return ['产能不能为负']
    return []
