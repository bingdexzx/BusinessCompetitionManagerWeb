// 统一错误提示翻译（面向最终用户的**中文、简洁**文案）。
// 规则：后端 {code,message} 已中文化 → 直接用；网络/超时/JS 运行时等技术错误 → 映射为友好中文；
// 未识别错误 → 传入的上下文兜底文案（如「保存失败」）。原始错误打印到控制台便于排查。
import { ApiError } from '@/api/client'

/** 状态码 → 中文兜底（后端未带 message 时） */
const STATUS_TEXT: Record<number, string> = {
  0: '网络连接失败，请检查网络后重试',
  400: '请求参数有误',
  401: '登录已过期，请重新登录',
  403: '没有权限执行此操作',
  404: '请求的内容不存在',
  405: '不支持的请求方法',
  408: '请求超时，请稍后重试',
  409: '操作冲突，请刷新后重试',
  413: '上传内容过大',
  422: '数据校验未通过',
  429: '请求过于频繁，请稍后再试',
  500: '服务器内部错误，请稍后重试',
  502: '网关错误，请稍后重试',
  503: '服务器繁忙，请稍后重试',
  504: '服务器响应超时，请稍后重试',
}

/** 技术错误特征 → 中文文案（网络/超时/解析/取消等） */
const TECH_PATTERNS: Array<[RegExp, string]> = [
  [/failed to fetch|networkerror|network request failed|load failed/i, '网络连接失败，请检查网络后重试'],
  [/timeout|timed?\s*out|etimedout/i, '请求超时，请稍后重试'],
  [/aborted|aborterror/i, '请求已取消'],
  [/json|unexpected token|unexpected end/i, '服务返回数据异常，请稍后重试'],
  [/econnrefused|econnreset|socket hang up/i, '无法连接服务器，请确认后端已启动'],
  [/quota|storage/i, '本地存储空间不足'],
  [/cannot read propert|undefined is not|null is not|is not a function/i, '页面异常，请刷新后重试'],
]

const CJK = /[\u4e00-\u9fa5]/ // 含中文视为已本地化的有效提示

/**
 * 把任意异常翻译成**简洁中文**提示。
 * @param err 捕获到的异常（ApiError / Error / 字符串 / 任意）
 * @param fallback 上下文兜底文案（如「保存失败」「加载失败」）
 */
export function errorMessage(err: unknown, fallback = '操作失败'): string {
  // 1) 后端业务错误：message 已是中文业务语义（含字段级校验原因），直接用
  if (err instanceof ApiError) {
    if (err.message && CJK.test(err.message)) return err.message
    return STATUS_TEXT[err.status] || fallback
  }
  // 2) 字符串错误（自 throw 的中文提示等）
  if (typeof err === 'string' && err.trim()) {
    return CJK.test(err) ? err : fallback
  }
  // 3) JS 运行时/网络错误：按特征翻译
  if (err instanceof Error) {
    for (const [pattern, text] of TECH_PATTERNS) {
      if (pattern.test(err.message)) return text
    }
    // 已本地化的自定义 Error 直接用；否则给兜底（原始信息进控制台）
    if (CJK.test(err.message)) return err.message
    console.error('[未翻译的错误]', err)
    return fallback
  }
  // 4) 未知类型
  if (err !== null && err !== undefined) console.error('[未知错误]', err)
  return fallback
}
