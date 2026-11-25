"""展示层中文映射（字段值操作类型等英文代号 → 中文）。

效果算子（ADD/SUB/SET）的中文名来自 ``plugins_runtime.ops`` 唯一事实源；
其余代号为字段日志专用（MIGRATE/CALC/CREATE/DELETE），在此补充。
与前端 utils/fieldOps.ts 保持同一套词表（仅展示用，语义以 ops 模块为准）。
"""

from plugins_runtime.ops import OP_LABELS as EFFECT_OP_LABELS

OP_LABELS = {
    **EFFECT_OP_LABELS,
    'MIGRATE': '迁移',
    'CALC': '重算',
    'CREATE': '创建',
    'DELETE': '删除',
}


def op_label(op) -> str:
    """字段操作类型中文（未知代号原样返回，不丢信息）。"""
    return OP_LABELS.get(op, op or '—')
