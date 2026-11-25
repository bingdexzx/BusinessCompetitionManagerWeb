// 工具箱三个计算器共用的小工具

/** 数量/金额展示：最多 4 位小数，去掉末尾多余的 0 */
export function formatNumber(value: number | string | null | undefined, digits = 4): string {
  const num = Number(value)
  if (!Number.isFinite(num)) return '0'
  return String(Number(num.toFixed(digits)))
}

/** 产地字段：JSON 数组字符串（["安山","北安"]），兼容逗号分隔的旧数据 */
export function parseOriginList(value: unknown): string[] {
  if (!value) return []
  if (Array.isArray(value)) return value.map((item) => String(item)).filter(Boolean)
  if (typeof value === 'object') return []
  const text = String(value).trim()
  if (!text) return []
  if (text.startsWith('[')) {
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) return parsed.map((item) => String(item)).filter(Boolean)
    } catch {
      return []
    }
    return []
  }
  return text
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

/** node_prices 这类 JSON 对象字段：{ "123": 45.5 } */
export function parseJsonObject(value: unknown): Record<string, unknown> {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>
  if (typeof value !== 'string') return {}
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : {}
  } catch {
    return {}
  }
}
