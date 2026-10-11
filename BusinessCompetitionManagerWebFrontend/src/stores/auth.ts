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

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(getAccessToken())
  const refreshToken = ref(getRefreshToken())
  const user = ref<User | null>(null)
  const selectedCompetitionId = ref<number | null>(
    getCompetitionId() ? Number(getCompetitionId()) : null,
  )

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

  async function updateProfile(payload: UpdateMePayload): Promise<void> {
    applyUser(await api.updateMe(payload))
  }

  function selectCompetition(id: number | string | null): void {
    const next = id === null || id === '' ? null : Number(id)
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
    updateProfile,
    selectCompetition,
    logout,
    clearSession,
  }
})
