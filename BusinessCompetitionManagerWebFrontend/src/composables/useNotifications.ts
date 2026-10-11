// WebSocket 实时通知客户端（§5.1：/ws/notifications，JWT 鉴权 + 自动重连）
import { computed, onBeforeUnmount, ref } from 'vue'
import { getAccessToken } from '@/api/client'

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

const handlers = new Set<Handler>()
const connected = ref(false)
const lastMessage = ref<NotificationPayload | null>(null)
const unreadCount = ref(0)

let socket: WebSocket | null = null
let retryTimer: ReturnType<typeof setTimeout> | null = null
let retryDelay = 1000
let started = false

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/notifications?token=${encodeURIComponent(getAccessToken())}`
}

function connect(): void {
  const token = getAccessToken()
  if (!token) return
  try {
    socket = new WebSocket(wsUrl())
  } catch {
    scheduleReconnect()
    return
  }

  socket.onopen = () => {
    connected.value = true
    retryDelay = 1000
  }
  socket.onmessage = (event: MessageEvent) => {
    try {
      const data = JSON.parse(String(event.data)) as NotificationPayload
      if (data.type === 'pong') return
      lastMessage.value = data
      if (data.type === 'notification') unreadCount.value += 1
      handlers.forEach((handler) => handler(data))
    } catch {
      // 忽略非 JSON 帧
    }
  }
  socket.onclose = () => {
    connected.value = false
    scheduleReconnect()
  }
  socket.onerror = () => {
    socket?.close()
  }
}

function scheduleReconnect(): void {
  if (retryTimer) return
  retryTimer = setTimeout(() => {
    retryTimer = null
    retryDelay = Math.min(retryDelay * 2, 30_000)
    connect()
  }, retryDelay)
}

/** 启动连接（幂等；登录后调用） */
export function startNotifications(): void {
  if (started) return
  started = true
  connect()
}

/** 登出/换账号时断开 */
export function stopNotifications(): void {
  started = false
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  socket?.close()
  socket = null
  connected.value = false
  unreadCount.value = 0
}

export function resetUnread(): void {
  unreadCount.value = 0
}

/** 组件内订阅实时通知（自动清理） */
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
