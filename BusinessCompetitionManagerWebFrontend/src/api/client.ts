// 统一 fetch 封装：自动携带 Bearer / X-Device-Screen / X-Competition-Id；401 自动 refresh 后重放一次，失败跳登录
import type { ApiErrorBody } from './types'

const API_BASE = '/api'

const ACCESS_TOKEN_KEY = 'bcm.access'
const REFRESH_TOKEN_KEY = 'bcm.refresh'
const COMPETITION_ID_KEY = 'bcm.competitionId'

export class ApiError extends Error {
  readonly code: number
  readonly status: number
  readonly details: unknown

  constructor(message: string, code: number, status: number, details: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_TOKEN_KEY) ?? ''
}

export function getRefreshToken(): string {
  return localStorage.getItem(REFRESH_TOKEN_KEY) ?? ''
}

export function setTokens(access: string, refresh?: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, access)
  if (refresh !== undefined) {
    localStorage.setItem(REFRESH_TOKEN_KEY, refresh)
  }
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
}

export function getCompetitionId(): string {
  return localStorage.getItem(COMPETITION_ID_KEY) ?? ''
}

export function setCompetitionId(id: number | string | null): void {
  if (id === null || id === '') {
    localStorage.removeItem(COMPETITION_ID_KEY)
  } else {
    localStorage.setItem(COMPETITION_ID_KEY, String(id))
  }
}

// 登录失效处理由 main.ts 注册，避免模块循环依赖
let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  /** 查询参数，自动过滤 undefined / null / '' */
  query?: Record<string, string | number | boolean | undefined | null>
  headers?: Record<string, string>
  /** 覆盖 X-Competition-Id（不传则使用全局选中的比赛） */
  competitionId?: number | string | null
  skipAuth?: boolean
  /** 公开接口但有 token 就带上：计入本人额度，而非同机标签页共享的「匿名（按 IP）」额度；token 失效自动降级匿名重试，不报错也不登出 */
  optionalAuth?: boolean
  skipRefresh?: boolean
}

function buildQuery(query: RequestOptions['query']): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue
    params.set(key, String(value))
  }
  const str = params.toString()
  return str ? `?${str}` : ''
}

function deviceScreen(): string {
  if (typeof window === 'undefined' || !window.screen) return ''
  return `${window.screen.width}x${window.screen.height}`
}

function makeTraceId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `trace-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return text
  }
}

function toApiError(res: Response, body: unknown): ApiError {
  // 中文兜底：不把 HTML 错误页/技术细节直接抛给用户
  const STATUS_TEXT: Record<number, string> = {
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
  const fallback = STATUS_TEXT[res.status] || `请求失败（HTTP ${res.status}）`
  if (body && typeof body === 'object') {
    const err = body as Partial<ApiErrorBody>
    return new ApiError(
      typeof err.message === 'string' && err.message ? err.message : fallback,
      typeof err.code === 'number' ? err.code : res.status,
      res.status,
      err.details ?? body,
    )
  }
  const isShortChinese =
    typeof body === 'string' && body.length <= 200 && /[\u4e00-\u9fa5]/.test(body)
  return new ApiError(isShortChinese ? (body as string) : fallback, res.status, res.status, body)
}

let refreshPromise: Promise<boolean> | null = null

/** 用 refresh 换新 access；并发请求共享同一次刷新 */
async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refresh = getRefreshToken()
      if (!refresh) return false
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh }),
        })
        if (!res.ok) return false
        const data = (await res.json()) as { access?: string; refresh?: string }
        if (!data.access) return false
        setTokens(data.access, data.refresh)
        return true
      } catch {
        return false
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

function accessTokenExp(token: string): number {
  if (!token) return 0
  try {
    const part = token.split('.')[1]
    if (!part) return 0
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const json = JSON.parse(atob(b64.padEnd(Math.ceil(b64.length / 4) * 4, '='))) as {
      exp?: number
    }
    return typeof json.exp === 'number' ? json.exp : 0
  } catch {
    return 0
  }
}

/** WS 握手只带 URL 里的 token，过期会在 accept 之前被拒（浏览器只拿到 1006）→ 握手前必须先换新；
 *  会话确实失效时返回 ''（调用方应停止重连）。 */
export async function ensureFreshAccessToken(
  opts: { force?: boolean; skewSeconds?: number } = {},
): Promise<string> {
  const token = getAccessToken()
  const exp = accessTokenExp(token)
  const now = Date.now() / 1000
  // 把「即将过期」也当作过期，避免握手途中失效
  const skew = Math.max(0, opts.skewSeconds ?? 30)
  const unexpired = Boolean(token) && (!exp || exp > now + skew)
  if (unexpired && !opts.force) return token
  if (!getRefreshToken()) return unexpired ? token : ''
  if (await refreshAccessToken()) return getAccessToken()
  return unexpired ? token : '' // 刷新失败：未过期就照用，过期则视为会话失效
}

async function requestOnce<T>(path: string, options: RequestOptions, retried: boolean): Promise<T> {
  const method = options.method ?? 'GET'
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Device-Screen': deviceScreen(),
    'X-Trace-Id': makeTraceId(),
    ...options.headers,
  }

  const token = options.skipAuth ? '' : getAccessToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const competitionId =
    options.competitionId !== undefined ? options.competitionId : getCompetitionId()
  if (competitionId !== null && competitionId !== '') {
    headers['X-Competition-Id'] = String(competitionId)
  }

  let payload: BodyInit | undefined
  if (options.body !== undefined) {
    if (options.body instanceof FormData) {
      // multipart 上传：不设 Content-Type，由浏览器自动带 boundary
      payload = options.body
    } else {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(options.body)
    }
  }

  const res = await fetch(`${API_BASE}${path}${buildQuery(options.query)}`, {
    method,
    headers,
    body: payload,
  })

  // 公开接口带了失效 token：降级为匿名重试（不刷新、不登出），保证注册页/档案页仍可用
  if (res.status === 401 && options.optionalAuth && !options.skipAuth && !retried) {
    return requestOnce<T>(path, { ...options, skipAuth: true }, true)
  }

  if (res.status === 401 && !options.skipRefresh && !retried && !options.skipAuth) {
    const refreshed = await refreshAccessToken()
    if (refreshed) {
      return requestOnce<T>(path, options, true)
    }
    clearTokens()
    unauthorizedHandler?.()
    const body = await parseBody(res)
    throw toApiError(res, body)
  }

  const body = await parseBody(res)
  if (!res.ok) {
    throw toApiError(res, body)
  }
  return body as T
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestOnce<T>(path, options, false)
}

export const http = {
  get<T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
    return request<T>(path, { ...options, method: 'GET' })
  },
  post<T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
    return request<T>(path, { ...options, method: 'POST', body })
  },
  patch<T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
    return request<T>(path, { ...options, method: 'PATCH', body })
  },
  put<T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
    return request<T>(path, { ...options, method: 'PUT', body })
  },
  delete<T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
    return request<T>(path, { ...options, method: 'DELETE' })
  },
}
