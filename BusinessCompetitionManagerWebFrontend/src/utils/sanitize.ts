/**
 * 极简 HTML/SVG 清洗：只用于「后台维护的奖牌样式」这类必须按标记渲染的字段。
 *
 * 规则（白名单思路）：
 * - 去掉 <script>/<style>/<iframe>/<object>/<embed>/<link>/<meta> 整个标签；
 * - 去掉所有 on* 事件属性与 javascript:/data:text/html 链接；
 * - 保留常见 SVG 标签与 class/style/attribute（奖牌样式需要）。
 *
 * 不是通用 sanitizer：若将来渲染用户自由输入的内容，请改用 DOMPurify。
 */
const DANGEROUS_TAGS = /<\s*(script|style|iframe|object|embed|link|meta)\b[\s\S]*?<\s*\/\s*\1\s*>/gi
const DANGEROUS_SELF_CLOSING = /<\s*(script|style|iframe|object|embed|link|meta)\b[^>]*\/?>/gi
const EVENT_ATTRS = /\son[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi
const DANGEROUS_URLS = /(href|src|xlink:href)\s*=\s*("|')\s*(javascript:|data:text\/html)[^"']*\2/gi

export function sanitizeMarkup(raw: string | null | undefined): string {
  let html = String(raw ?? '')
  if (!html) return ''
  html = html.replace(DANGEROUS_TAGS, '')
  html = html.replace(DANGEROUS_SELF_CLOSING, '')
  html = html.replace(EVENT_ATTRS, '')
  html = html.replace(DANGEROUS_URLS, '$1=""')
  return html
}
