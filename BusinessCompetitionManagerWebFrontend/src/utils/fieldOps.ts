// 字段值操作类型 / 字段日志事件的中文展示映射
//（效果审计 op、字段日志 op：ADD/SUB/SET/MIGRATE 等英文代号 → 中文）

const OP_LABELS: Record<string, string> = {
  ADD: '增加',
  SUB: '减少',
  SET: '设置',
  MIGRATE: '迁移',
  CALC: '重算',
  CREATE: '创建',
  DELETE: '删除',
}

const EVENT_LABELS: Record<string, string> = {
  VALUE_CHANGE: '值变更',
  SCHEMA_CHANGE: '结构变更',
}

/** 操作类型中文（未知代号原样返回） */
export function opLabel(op: string | null | undefined): string {
  if (!op) return '—'
  return OP_LABELS[op] ?? op
}

/** 字段日志事件中文（未知代号原样返回） */
export function eventLabel(event: string | null | undefined): string {
  if (!event) return '—'
  return EVENT_LABELS[event] ?? event
}
