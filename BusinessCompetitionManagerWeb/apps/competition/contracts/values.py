"""合同效果取值/算子（公司字段与区域字段共用的纯逻辑）。"""

from plugins_runtime import ops

from .errors import ContractError


def resolve_effect_company(effect, companies: dict):
    """Effect.company 可以是参与方角色或公司名（§7.2）。"""
    if effect.company in companies:
        return companies[effect.company]
    for company in companies.values():
        if company.name == effect.company:
            return company
    raise ContractError(f'效果指向未知公司/角色：{effect.company}')


def effect_after(before, op: str, value):
    """算子计算（ADD/SUB/SET…），统一由 plugins_runtime.ops 实现。"""
    return ops.apply(before, op, value)
