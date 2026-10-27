// WebSocket 实时通知客户端（§5.1：/ws/notifications，JWT 鉴权 + 自动重连）
import { computed, onBeforeUnmount, ref } from 'vue'
import { ensureFreshAccessToken, getAccessToken } from '@/api/client'

export interface NotificationPayload {
  type?: string
  id?: number
  kind?: string
  title?: string
  body?: string
  payload?: Record<string, unknown>
  createdAt?: string
  competitionId?: number
  competitionName?: string
}

type Handler = (message: NotificationPayload) => void

export interface ResourceChangeEvent {
  type?: string
  seq?: number
  resource?: string
  action?: string
  competitionId?: number | null
  payload?: Record<string, unknown>
  ts?: string
}

type ResourceHandler = (events: ResourceChangeEvent[]) => void

const handlers = new Set<Handler>()
const resourceHandlers = new Set<ResourceHandler>()
const connected = ref(false)
const lastMessage = ref<NotificationPayload | null>(null)
const unreadCount = ref(0)

let socket: WebSocket | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryDelay = 1000
let started = false
let globalSubscribed = false
const subscriptions = new Map<number, number>()
const pendingResourceEvents: ResourceChangeEvent[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null

const REPLAY_SEQ_PREFIX = 'gipfel:resource-seq:'
const ANON_USER_KEY = 'gipfel:anon-user:'
/** 系统级作用域：无比赛上下文的全局库资源（与后端 global 分组一致） */
const GLOBAL_SCOPE = 'global'

/** 控制帧（心跳/订阅确认/拒绝）：不得进入 lastMessage 或通知处理器 */
const CONTROL_TYPES = new Set([
  'pong',
  'resource:subscribed',
  'resource:unsubscribed',
  'resource:denied',
])

/** 从 JWT 解出用户 id：Django simplejwt 默认 user_id，兼容 userId/sub/uid/id */
function tokenUserId(token: string): string {
  if (!token) return ''
  try {
    const parts = token.split('.')
    if (parts.length < 2) return ''
    const payload = parts[1]
    if (!payload) return ''
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')
    const json = decodeURIComponent(
      window
        .atob(padded)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    )
    const claims = JSON.parse(json) as Record<string, unknown>
    const id = claims.user_id ?? claims.userId ?? claims.sub ?? claims.uid ?? claims.id
    if (id === undefined || id === null) return ''
    const str = String(id)
    return str && str !== 'null' && str !== 'undefined' ? str : ''
  } catch {
    return ''
  }
}

/** 用户桶键：优先 token user id，其次 localStorage 用户 id，都没有则落稳定匿名桶（刷新不变） */
function getUserKey(): string {
  const fromToken = tokenUserId(getAccessToken())
  if (fromToken) return fromToken
  try {
    const storedId = window.localStorage.getItem('bcm.userId')
    if (storedId) return storedId
    const userJson = window.localStorage.getItem('bcm.user')
    if (userJson) {
      const user = JSON.parse(userJson) as { id?: number | string } | null
      if (user?.id !== undefined && user.id !== null && String(user.id) !== '') {
        return String(user.id)
      }
    }
  } catch {
    // 忽略脏 localStorage
  }
  let anon = window.localStorage.getItem(ANON_USER_KEY)
  if (!anon) {
    anon =
      (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : '') || `anon-${Date.now()}-${Math.random().toString(16).slice(2)}`
    try {
      window.localStorage.setItem(ANON_USER_KEY, anon)
    } catch {
      // 存储不可用时退化为本次会话内匿名桶
    }
  }
  return anon
}

function scopeOf(ev: ResourceChangeEvent): string | number {
  return ev.competitionId ? ev.competitionId : GLOBAL_SCOPE
}

function seqKey(scope: string | number): string {
  return `${REPLAY_SEQ_PREFIX}${getUserKey()}:${scope}`
}

function loadSeq(scope: string | number): number {
  return Number(window.localStorage.getItem(seqKey(scope)) || 0)
}

function saveSeq(scope: string | number, seq: number): void {
  if (seq > 0) window.localStorage.setItem(seqKey(scope), String(seq))
}

function queueResourceEvents(events: ResourceChangeEvent[]): void {
  for (const ev of events) {
    const scope = scopeOf(ev)
    // seq 回退/重复：不重新投递、不降低游标（只在严格更大时推进）
    if (typeof ev.seq === 'number' && ev.seq <= loadSeq(scope)) continue
    pendingResourceEvents.push(ev)
  }
  if (flushTimer) return
  flushTimer = setTimeout(() => {
    flushTimer = null
    const batch = pendingResourceEvents.splice(0, pendingResourceEvents.length)
    if (batch.length) {
      resourceHandlers.forEach((handler) => handler(batch))
      // 处理器执行完再提交游标：崩溃不会跳过事件重放
      for (const ev of batch) {
        if (typeof ev.seq === 'number') saveSeq(scopeOf(ev), Math.max(loadSeq(scopeOf(ev)), ev.seq))
      }
    }
  }, 400)
}

function sendSubscribe(cid: number): void {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'subscribe', competitionId: cid }))
    // 断线期间可能漏事件：带上本地 seq 游标请求重放
    socket.send(JSON.stringify({ type: 'replay', competitionId: cid, lastSeq: loadSeq(cid) }))
  }
}

function sendSubscribeGlobal(): void {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'subscribe', scope: GLOBAL_SCOPE }))
    socket.send(
      JSON.stringify({ type: 'replay', scope: GLOBAL_SCOPE, lastSeq: loadSeq(GLOBAL_SCOPE) }),
    )
  }
}

function wsUrl(token: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/notifications?token=${encodeURIComponent(token)}`
}

let openedAt = 0
/** 下次连接前强制换新 token（握手被拒时置位，避免拿失效 token 空转重连） */
let forceRefreshNext = false

async function connect(): Promise<void> {
  if (!started) return
  // WS 握手只带 URL 里的 token，没有 401 重放机会：过期就地先刷新，否则必然握手失败
  const token = await ensureFreshAccessToken({ force: forceRefreshNext })
  forceRefreshNext = false
  if (!started) return
  if (!token) {
    // 无可用会话（无 token 或已过期且刷新失败）：停止空转重连，交由 HTTP 层引导重新登录
    started = false
    return
  }
  try {
    socket = new WebSocket(wsUrl(token))
  } catch {
    scheduleReconnect()
    return
  }

  socket.onopen = () => {
    openedAt = Date.now()
    connected.value = true
    retryDelay = 1000
    if (globalSubscribed) sendSubscribeGlobal()
    subscriptions.forEach((_seq, cid) => sendSubscribe(cid))
  }
  socket.onmessage = (event: MessageEvent) => {
    try {
      const data = JSON.parse(String(event.data)) as NotificationPayload & {
        events?: ResourceChangeEvent[]
      }
      if (!data.type || CONTROL_TYPES.has(data.type)) return
      if (data.type === 'resource:changed') {
        queueResourceEvents([data as ResourceChangeEvent])
        return
      }
      if (data.type === 'resource:replay') {
        if (Array.isArray(data.events) && data.events.length) {
          queueResourceEvents(data.events)
        }
        return
      }
      lastMessage.value = data
      if (data.type === 'notification') unreadCount.value += 1
      handlers.forEach((handler) => handler(data))
    } catch {
      // 忽略非 JSON 帧
    }
  }
  socket.onclose = () => {
    connected.value = false
    const lived = openedAt ? Date.now() - openedAt : 0
    openedAt = 0
    if (lived < 1000) forceRefreshNext = true
    scheduleReconnect()
  }
  socket.onerror = () => {
    socket?.close()
  }
}

function scheduleReconnect(): void {
  if (!started || retryTimer) return
  retryTimer = setTimeout(() => {
    retryTimer = null
    if (!started) return
    retryDelay = Math.min(retryDelay * 2, 30_000)
    void connect()
  }, retryDelay)
}

export function startNotifications(): void {
  if (started) return
  started = true
  void connect()
}

export function stopNotifications(): void {
  started = false
  globalSubscribed = false
  openedAt = 0
  forceRefreshNext = false
  subscriptions.clear()
  pendingResourceEvents.length = 0
  if (flushTimer) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  socket?.close()
  socket = null
  connected.value = false
  unreadCount.value = 0
}

export function subscribeCompetition(cid: number | string): void {
  const id = Number(cid)
  if (!id) return
  if (!subscriptions.has(id)) subscriptions.set(id, loadSeq(id))
  sendSubscribe(id)
}

export function unsubscribeCompetition(cid: number | string): void {
  const id = Number(cid)
  if (!subscriptions.delete(id)) return
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'unsubscribe', competitionId: id }))
  }
}

/** 订阅系统级资源变更（登录后常驻；重连自动恢复 + 本地 seq 游标重放） */
export function subscribeGlobal(): void {
  globalSubscribed = true
  sendSubscribeGlobal()
}

/** 组件内订阅资源变更：400ms 去抖合并后回调事件批次（通常就在回调里增量重拉） */
export function useResourceChanged(handler: ResourceHandler) {
  resourceHandlers.add(handler)
  onBeforeUnmount(() => resourceHandlers.delete(handler))
  return { connected }
}

/** 资源变更 → 自动刷新：只按声明的资源触发（防刷新风暴）；后台标签页只标脏、回前台再刷新；组件卸载自动解绑。
 *  @param resources 资源名（后端按路径推导：contracts/teams/users/fiscal-years…；'all' = 任意变更） */
export function useResourceRefresh(
  resources: string[] | 'all',
  loader: () => void | Promise<void>,
) {
  const wanted = resources === 'all' ? null : new Set(resources)
  let dirtyWhileHidden = false

  const run = (): void => {
    dirtyWhileHidden = false
    void loader()
  }
  const onVisibilityChange = (): void => {
    if (!document.hidden && dirtyWhileHidden) run()
  }

  const { connected } = useResourceChanged((events) => {
    const hit = events.some((ev) => !wanted || wanted.has(String(ev.resource || '')))
    if (!hit) return
    if (document.hidden) {
      dirtyWhileHidden = true // 后台页先标脏，回前台统一刷新
      return
    }
    run()
  })

  document.addEventListener('visibilitychange', onVisibilityChange)
  onBeforeUnmount(() => document.removeEventListener('visibilitychange', onVisibilityChange))
  return { connected }
}

export function resetUnread(): void {
  unreadCount.value = 0
}

export function useNotifications(handler?: Handler) {
  if (handler) {
    handlers.add(handler)
    onBeforeUnmount(() => handlers.delete(handler))
  }
  return {
    connected,
    lastMessage,
    unreadCount: computed(() => unreadCount.value),
    startNotifications,
    stopNotifications,
    resetUnread,
  }
}
