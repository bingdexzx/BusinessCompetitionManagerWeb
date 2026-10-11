// 展示用的小工具
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}

/** JSON / 对象转展示文本 */
export function toDisplay(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/** 字符串截断（表格里展示 UA / 摘要） */
export function truncate(value: string | null | undefined, max = 40): string {
  if (!value) return '—'
  return value.length > max ? `${value.slice(0, max)}…` : value
}
