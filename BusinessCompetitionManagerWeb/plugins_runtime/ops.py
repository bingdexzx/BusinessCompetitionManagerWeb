"""落账算子（Effect op）的唯一事实源（§7.2 效果审计 / §8.1 插件协议）。

插件的 ``Effect(company, field, op, value)`` 里的 op 是**数据**而不是代码：
落账审计、账本重演（ledger）、回滚（engine.rollback_round）、展示词表都只依赖
本模块的纯函数，禁止再在其他地方重复实现同一套算子语义。

约定（与历史行为完全一致，改动需同步迁移与测试）：
- ``ADD``/``SUB``：数值增量（非数值按 0 计）；
- ``SET``：直接覆盖为给定值，无算术逆（回滚 = 恢复落账前快照 before_raw）。
"""

ADD = 'ADD'
SUB = 'SUB'
SET = 'SET'

OPS = (ADD, SUB, SET)
OP_LABELS = {ADD: '增加', SUB: '减少', SET: '设置'}

_INVERSE = {ADD: SUB, SUB: ADD}


def is_valid(op) -> bool:
    """op 是否属于合法算子集合（Effect 构造时校验用）。"""
    return op in OPS


def label(op) -> str:
    """算子中文名（未知代号原样返回，不丢信息）。"""
    return OP_LABELS.get(op, op or '—')


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def apply(before, op, value):
    """把 value 按算子落到 before 上，返回变更后值。

    未知算子按 SET 处理（与历史实现一致，便于旧审计数据重演）。
    """
    if op == ADD:
        return _num(before) + _num(value)
    if op == SUB:
        return _num(before) - _num(value)
    return value


def inverse(op):
    """算术逆算子：ADD↔SUB；SET（及未知算子）无逆，返回 None。"""
    return _INVERSE.get(op)


def inverse_apply(before, op, value, before_raw):
    """回滚一条效果 → ``(after, inverse_op)``；SET 恢复落账前快照。"""
    inv = inverse(op)
    if inv is None:
        return before_raw, SET
    return apply(before, inv, value), inv
