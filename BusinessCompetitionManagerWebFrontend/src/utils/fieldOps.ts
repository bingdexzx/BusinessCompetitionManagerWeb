// 字段操作代号 → 中文（效果审计 op、字段日志 op：ADD/SUB/SET/MIGRATE 等）

const OP_LABELS: Record<string, string> = {
  ADD: '增加',
  SUB: '减少',
  SET: '设置',
  MIGRATE: '迁移',
  CALC: '重算',
  CREATE: '创建',
  DELETE: '删除',
}

/** 操作类型中文（未知代号原样返回） */
export function opLabel(op: string | null | undefined): string {
  if (!op) return '—'
  return OP_LABELS[op] ?? op
}

