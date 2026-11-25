// 系统设置 — 流量限制接口（仅系统超级管理员）：/api/system/rate-limit
// 契约：配置/统计字段全部 camelCase；错误响应 { code, message, details }（message 中文）
import { http, request } from './client'

// ---------- 类型 ----------

/** 登录限流配置 */
export interface LoginRateLimitConfig {
  /** 窗口内失败次数上限 */
  failLimit: number
  /** 统计窗口（秒） */
  windowSeconds: number
  /** 锁定时长（秒） */
  lockSeconds: number
}

/** 四种角色的每分钟 API 请求限额 */
export interface ApiPerMinuteLimits {
  /** 超级管理员 */
  superuser: number
  /** 管理员（主席团） */
  admin: number
  /** 参赛代表 */
  player: number
  /** 匿名 / 无身份 */
  anonymous: number
}

/** API 限流配置 */
export interface ApiRateLimitConfig {
  /** 是否启用 API 限流 */
  enabled: boolean
  perMinute: ApiPerMinuteLimits
}

/** 流量限制配置整体（PUT 时作为请求体整体提交） */
export interface RateLimitConfig {
  login: LoginRateLimitConfig
  api: ApiRateLimitConfig
}

/** 限流统计 */
export interface RateLimitStats {
  /** 当前计数记录数（API 计数 + 登录失败计数） */
  throttleRecords: number
  /** 生效锁数 */
  activeLocks: number
}

/** GET /api/system/rate-limit 响应 */
export interface RateLimitSettings {
  config: RateLimitConfig
  stats: RateLimitStats
}

/** DELETE /api/system/rate-limit/records 响应 */
export interface ClearRateLimitRecordsResult {
  ok: boolean
  cleared: number
}

// ---------- 接口 ----------

/** GET /api/system/rate-limit 读取配置 + 统计 */
export function getRateLimit(): Promise<RateLimitSettings> {
  return http.get<RateLimitSettings>('/system/rate-limit')
}

/** PUT /api/system/rate-limit 整体保存配置（严格校验，非法字段 400），返回保存后的配置 */
export function saveRateLimit(config: RateLimitConfig): Promise<RateLimitConfig> {
  return request<RateLimitConfig>('/system/rate-limit', { method: 'PUT', body: config })
}

/** POST /api/system/rate-limit/reset 恢复默认配置，返回默认配置 */
export function resetRateLimit(): Promise<RateLimitConfig> {
  return http.post<RateLimitConfig>('/system/rate-limit/reset')
}

/** DELETE /api/system/rate-limit/records 清空全部限流记录（含登录限流） */
export function clearRateLimitRecords(): Promise<ClearRateLimitRecordsResult> {
  return http.delete<ClearRateLimitRecordsResult>('/system/rate-limit/records')
}
