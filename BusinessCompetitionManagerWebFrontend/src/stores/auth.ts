// 认证与身份状态：token 存 localStorage，用户信息、当前比赛上下文
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as api from '@/api'
import {
  clearTokens,
  getAccessToken,
  getCompetitionId,
  getRefreshToken,
  setCompetitionId,
  setTokens,
} from '@/api/client'
import type { LoginResponse, Membership, RegisterPayload, UpdateMePayload, User } from '@/api/types'

/** 只接受正整数 id；undefined/null/'NaN'/0 等一律归 null（防脏值污染比赛上下文） */
function sanitizeId(id: number | string | null | undefined): number | null {
  if (id === null || id === undefined || id === '') return null
  const next = Number(id)
  return Number.isInteger(next) && next > 0 ? next : null
}

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(getAccessToken())
  const refreshToken = ref(getRefreshToken())
  const user = ref<User | null>(null)
  // 仅接受正整数 id：历史脏值（'undefined'/'NaN'）会被清理，防止污染 X-Competition-Id
  const selectedCompetitionId = ref<number | null>(sanitizeId(getCompetitionId()))

  const isAuthenticated = computed(() => Boolean(accessToken.value))
  const isSuperuser = computed(() => Boolean(user.value?.isSuperuser))
  const memberships = computed<Membership[]>(() => user.value?.memberships ?? [])
  /** 当前选中比赛下我的身份 */
  const currentMembership = computed<Membership | null>(
    () => memberships.value.find((m) => m.id === selectedCompetitionId.value) ?? null,
  )
  const currentIdentityLabel = computed(() => currentMembership.value?.identityLabel ?? '')

  function applySession(session: LoginResponse): void {
    accessToken.value = session.access
    refreshToken.value = session.refresh
    setTokens(session.access, session.refresh)
    user.value = session.user
  }

  function applyUser(next: User): void {
    user.value = next
    // 选中的比赛已不再属于我时，清掉上下文
    if (
      selectedCompetitionId.value !== null &&
      !next.memberships.some((m) => m.id === selectedCompetitionId.value) &&
      !next.isSuperuser
    ) {
      selectCompetition(null)
    }
  }

  async function login(username: string, password: string): Promise<void> {
    applySession(await api.login(username, password))
  }

  async function register(payload: RegisterPayload): Promise<User> {
    return api.register(payload)
  }

  async function fetchMe(): Promise<void> {
    applyUser(await api.getMe())
  }

  /** 应用启动时恢复会话（有 token 就拉取当前用户） */
  async function init(): Promise<void> {
    if (!accessToken.value) return
    try {
      await fetchMe()
    } catch {
      // token 已失效：清空本地会话
      clearSession()
    }
  }

  // 会话补齐去重：启动时的 init() 与路由守卫的 ensureSession() 可能同时触发，
  // 不能并发拉两次 /me（否则互相覆盖 user，并多打一次请求）。
  let sessionPromise: Promise<void> | null = null

  /**
   * 确保「已登录且用户资料已加载」。
   *
   * 刷新页面或直接打开深链时，`main.ts` 的 `init()` 是异步的，而路由守卫同步执行——
   * 此刻 `user` 还是 null，`isSuperuser` / `memberships` 都是空，权限判断会把
   * 系统超管误判成无权限、把深链重定向回比赛列表。守卫必须先 await 这里。
   */
  async function ensureSession(): Promise<void> {
    if (!accessToken.value || user.value) return
    if (!sessionPromise) {
      sessionPromise = init().finally(() => {
        sessionPromise = null
      })
    }
    await sessionPromise
  }

  async function updateProfile(payload: UpdateMePayload): Promise<void> {
    applyUser(await api.updateMe(payload))
  }

  function selectCompetition(id: number | string | null): void {
    const next = sanitizeId(id)
    selectedCompetitionId.value = next
    setCompetitionId(next)
  }

  function clearSession(): void {
    accessToken.value = ''
    refreshToken.value = ''
    user.value = null
    clearTokens()
  }

  function logout(): void {
    clearSession()
    selectCompetition(null)
  }

  return {
    accessToken,
    refreshToken,
    user,
    selectedCompetitionId,
    isAuthenticated,
    isSuperuser,
    memberships,
    currentMembership,
    currentIdentityLabel,
    login,
    register,
    fetchMe,
    init,
    ensureSession,
    updateProfile,
    selectCompetition,
    logout,
    clearSession,
  }
})
