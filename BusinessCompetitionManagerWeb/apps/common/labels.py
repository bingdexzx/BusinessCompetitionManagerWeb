"""展示层中文映射（字段值操作类型等英文代号 → 中文）。

与前端 utils/fieldOps.ts 保持同一套词表（ADD 增加 / SUB 减少 / SET 设置 …）。
"""

OP_LABELS = {
    'ADD': '增加',
    'SUB': '减少',
    'SET': '设置',
    'MIGRATE': '迁移',
    'CALC': '重算',
    'CREATE': '创建',
    'DELETE': '删除',
}


def op_label(op) -> str:
    """字段操作类型中文（未知代号原样返回，不丢信息）。"""
    return OP_LABELS.get(op, op or '—')
