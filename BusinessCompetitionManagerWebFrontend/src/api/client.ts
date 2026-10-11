// 统一 fetch 封装：自动携带 Bearer / X-Device-Screen / X-Competition-Id，
// 401 时自动用 refresh 换新 access 并重放一次，失败则跳转登录页。
import type { ApiErrorBody } from './types'

const API_BASE = '/api'

const ACCESS_TOKEN_KEY = 'bcm.access'
const REFRESH_TOKEN_KEY = 'bcm.refresh'
const COMPETITION_ID_KEY = 'bcm.competitionId'

/** 统一抛出的 API 错误（后端错误响应 { code, message, details }） */
export class ApiError extends Error {
  /** 后端业务错误码 */
  readonly code: number
  /** HTTP 状态码 */
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

// ---------- token / 上下文 存取（localStorage 持久化） ----------

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

// ---------- 登录失效处理（由 main.ts 注册，避免模块循环依赖） ----------

let unauthorizedHandler: (() => void) | null = null

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

// ---------- 请求 ----------

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** JSON 请求体 */
  body?: unknown
  /** 查询参数，自动过滤 undefined / null / '' */
  query?: Record<string, string | number | boolean | undefined | null>
  /** 附加请求头 */
  headers?: Record<string, string>
  /** 覆盖 X-Competition-Id（不传则使用全局选中的比赛） */
  competitionId?: number | string | null
  /** 跳过鉴权头（登录/注册/学校搜索等公开接口） */
  skipAuth?: boolean
  /** 禁止 401 自动刷新重放（refresh 接口自身使用） */
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
  const fallback = `请求失败（HTTP ${res.status}）`
  if (body && typeof body === 'object') {
    const err = body as Partial<ApiErrorBody>
    return new ApiError(
      typeof err.message === 'string' && err.message ? err.message : fallback,
      typeof err.code === 'number' ? err.code : res.status,
      res.status,
      err.details ?? body,
    )
  }
  return new ApiError(typeof body === 'string' && body ? body : fallback, res.status, res.status, body)
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

  // 401：尝试刷新 token 后重放一次
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
  delete<T>(path: string, options: Omit<RequestOptions, 'method' | 'body'> = {}): Promise<T> {
    return request<T>(path, { ...options, method: 'DELETE' })
  },
}
