// 用户管理接口（仅系统超管可用）：/api/users 账号列表/新建/详情/修改/删除/重置密码
// 契约：字段全部 camelCase；错误响应 { code, message, details }（message 中文）
import { http } from './client'

// ---------- 类型 ----------

/** 学校概要 */
export interface UserAdminSchool {
  id: number
  name: string
}

/** 比赛身份概要（memberships） */
export interface UserMembershipSummary {
  competitionId: number
  identity: string
  managedCompanies: number[]
}

/** 账号列表项 / 详情 */
export interface UserAdminItem {
  id: number
  username: string
  displayName: string
  email: string | null
  school: UserAdminSchool | null
  isSuperuser: boolean
  isActive: boolean
  createdAt: string
  memberships: UserMembershipSummary[]
}

/** 账号列表分页结果 */
export interface UserAdminPage {
  items: UserAdminItem[]
  total: number
  page: number
  pageSize: number
}

/** 列表查询参数 */
export interface UserAdminQuery {
  page?: number
  pageSize?: number
  /** 模糊匹配 username / displayName / email */
  q?: string
}

/** 新建账号 */
export interface CreateUserPayload {
  username: string
  /** 8-128 位 */
  password: string
  displayName: string
  email?: string
  schoolId?: number | null
  isSuperuser?: boolean
}

/** 修改账号（部分更新） */
export interface UpdateUserPayload {
  displayName?: string
  email?: string | null
  schoolId?: number | null
  isActive?: boolean
  isSuperuser?: boolean
}

/** 重置密码结果（旧 JWT 全部失效） */
export interface ResetPasswordResult {
  ok: boolean
  message?: string
}

// ---------- 接口 ----------

/** GET /api/users 账号列表（分页 + 关键词搜索） */
export function getUsers(query: UserAdminQuery = {}): Promise<UserAdminPage> {
  return http.get<UserAdminPage>('/users', {
    query: { page: query.page, pageSize: query.pageSize, q: query.q },
  })
}


/** POST /api/users 新建账号 */
export function createUser(payload: CreateUserPayload): Promise<UserAdminItem> {
  return http.post<UserAdminItem>('/users', payload)
}

/** PATCH /api/users/<id> 修改 displayName/email/schoolId/isActive/isSuperuser */
export function updateUser(id: number, payload: UpdateUserPayload): Promise<UserAdminItem> {
  return http.patch<UserAdminItem>(`/users/${id}`, payload)
}

/** DELETE /api/users/<id> 删除账号（不能删自己 / 最后一个系统超管，后端拒绝） */
export function deleteUser(id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/users/${id}`)
}

/** POST /api/users/<id>/password 重置密码（8-128 位），已发 JWT 全部失效（顶号） */
export function resetUserPassword(id: number, password: string): Promise<ResetPasswordResult> {
  return http.post<ResetPasswordResult>(`/users/${id}/password`, { password })
}
