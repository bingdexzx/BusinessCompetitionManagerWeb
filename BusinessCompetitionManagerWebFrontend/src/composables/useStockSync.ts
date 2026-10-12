// 股票同步客户端（大数据量同步优化的性能核心，契约 docs/股票模块与同步优化.md §4.2/§5）
//
// 机制一览：
// 1. snapshot 起步（since 传空）→ 之后 delta 游标合并：游标永远用上一响应的 serverTime（规避客户端时钟偏差）；
//    Map by code/id 幂等覆盖（stocks 按 code、candles 按 code#round、orders/holdings/accounts 按 id）。
// 2. in-flight 去重：上一次 /stock/sync 未返回前不发新请求；期间合并进来的请求排队成一轮补充同步。
// 3. 去抖 1.5s：WS 信号 / 轮询合并成一次 /stock/sync（首个信号起设最大等待，防连续信号饿死）。
// 4. 页面不可见退避 10s（document.visibilitychange）：隐藏时同步窗口放宽到 10s，重新可见立即补一次。
// 5. 失败自动回退 snapshot：增量失败即作废游标、重拉快照重试一次。
//
// 性能红线：大列表一律 shallowRef + 整体替换数组（不做逐项响应式代理），
// 视图侧按 50/页切片渲染；同步只走 /stock/sync，不拉无谓全量。
import { ref, shallowRef, toValue, type MaybeRefOrGetter } from 'vue'
import { syncStockMarket } from '@/api'
import { ApiError } from '@/api/client'
import { errorMessage } from '@/utils/errors'
import type {
  Stock,
  StockCandle,
  StockFundsAccount,
  StockHolding,
  StockOrder,
  StockSyncPage,
} from '@/api/types'

/** 去抖窗口：WS 信号/轮询合并成一次 /stock/sync */
const DEBOUNCE_MS = 1500
/** 页面不可见时的退避窗口 */
const HIDDEN_DEBOUNCE_MS = 10_000
/** 单次增量 /stock/sync 的 limit（契约 §4.2 默认 500） */
const SYNC_LIMIT = 500
/** 快照起步用服务端上限（SYNC_MAX_LIMIT=2000）一次拉足，降低快照被 limit 截断的概率 */
const SNAPSHOT_LIMIT = 2000
/** hasMore 连续拉取的安全上限（防服务端异常导致死循环） */
const MAX_PAGES_PER_SYNC = 50

// ---------- 共享状态（模块级单例：行情看板 / 交易管理共用同一条同步通道） ----------

/** 股票（薄字段，按 code 幂等覆盖） */
const stocks = shallowRef<Stock[]>([])
/** K 线（按 stockCode#round 幂等覆盖） */
const candles = shallowRef<StockCandle[]>([])
/** 我的委托（按 id 幂等覆盖） */
const orders = shallowRef<StockOrder[]>([])
/** 我的持仓（按 id 幂等覆盖） */
const holdings = shallowRef<StockHolding[]>([])
/** 我的资金账户（按 id 幂等覆盖） */
const accounts = shallowRef<StockFundsAccount[]>([])
/** 当前轮次（同步响应携带） */
const round = ref(0)
/** 上次同步时间（同时也是下次增量游标） */
const lastSyncAt = ref('')
/** 同步进行中 */
const syncing = ref(false)
/** 最近一次同步失败原因（后台自动同步静默记录，手动同步由调用方统一弹错） */
const lastError = ref('')
/** 比赛不存在/已删除（404）：同步已终止，页面提示返回比赛列表 */
const missing = ref(false)

// 合并缓冲：先 Map 幂等覆盖，再整体发布为浅引用数组
const stockByCode = new Map<string, Stock>()
const candleByKey = new Map<string, StockCandle>()
const orderById = new Map<string | number, StockOrder>()
const holdingById = new Map<string | number, StockHolding>()
const accountById = new Map<string | number, StockFundsAccount>()

/** 增量游标（空串 = 下次走 snapshot 快照） */
let cursor = ''
/** 当前绑定的比赛 id */
let boundCid = ''
/** start/stop 引用计数（两页同时挂载时共享一条通道） */
let refCount = 0
let debounceTimer: ReturnType<typeof setTimeout> | null = null
/** 首个待同步信号到达时间（最大等待用） */
let firstPendingAt = 0
/** 当前 in-flight 的同步（去重锚点） */
let inflight: Promise<void> | null = null
/** in-flight 期间又来了同步请求：结束后补一轮 */
let rerunPending = false
/** in-flight 期间要求强制快照 */
let fullPending = false

// ---------- 合并键（id 缺失时退化为业务键，保证幂等覆盖） ----------

function orderKey(o: StockOrder): string | number {
  return typeof o.id === 'number' ? o.id : `${o.fundsAccountId}#${o.stockCode}#${o.createdAt}`
}

function holdingKey(h: StockHolding): string | number {
  return typeof h.id === 'number' ? h.id : `${h.fundsAccountId}#${h.stockCode}`
}

function accountKey(a: StockFundsAccount): string | number {
  return typeof a.id === 'number' ? a.id : `${a.ownerType}#${a.companyId ?? a.userId}`
}

// ---------- 本地合并与发布 ----------

/** 整体发布（浅引用替换一次，视图按分页切片重算；避免逐项响应式开销） */
function publish(): void {
  stocks.value = [...stockByCode.values()].sort((a, b) => String(a.code).localeCompare(String(b.code)))
  candles.value = [...candleByKey.values()].sort(
    (a, b) => String(a.stockCode).localeCompare(String(b.stockCode)) || a.round - b.round,
  )
  orders.value = [...orderById.values()].sort((a, b) => {
    // 新单在前（乐观占位行 id 为负，用 createdAt 兜底排到最上面）
    const ta = Date.parse(a?.createdAt ?? '') || 0
    const tb = Date.parse(b?.createdAt ?? '') || 0
    return tb - ta || (b.id ?? 0) - (a.id ?? 0)
  })
  holdings.value = [...holdingById.values()].sort((a, b) => (a.id ?? 0) - (b.id ?? 0))
  accounts.value = [...accountById.values()].sort((a, b) => (a.id ?? 0) - (b.id ?? 0))
}

function clearLocal(): void {
  stockByCode.clear()
  candleByKey.clear()
  orderById.clear()
  holdingById.clear()
  accountById.clear()
  publish()
}

/** 幂等合并一页同步数据（同 code/id 直接覆盖取新） */
function applyPage(page: StockSyncPage): void {
  for (const s of page.stocks ?? []) {
    if (s && s.code != null) stockByCode.set(String(s.code), s)
  }
  for (const c of page.candles ?? []) {
    if (c && c.stockCode != null && typeof c.round === 'number') {
      candleByKey.set(`${c.stockCode}#${c.round}`, c)
    }
  }
  for (const o of page.orders ?? []) {
    if (o) orderById.set(orderKey(o), o)
  }
  for (const h of page.holdings ?? []) {
    if (h) holdingById.set(holdingKey(h), h)
  }
  for (const a of page.accounts ?? []) {
    if (a) accountById.set(accountKey(a), a)
  }
  if (typeof page.round === 'number' && page.round > 0) round.value = page.round
  publish()
}

/** 切换比赛：本地状态整体重置，重新快照起步 */
function switchCid(next: string): void {
  if (!next || next === boundCid) return
  boundCid = next
  cursor = ''
  lastSyncAt.value = ''
  lastError.value = ''
  round.value = 0
  clearLocal()
}

// ---------- 同步执行（快照/增量 + hasMore 续拉 + 失败回退） ----------

/** 拉取一页到多页同步数据并合并 */
async function syncOnce(full: boolean): Promise<void> {
  const targetCid = boundCid
  if (full) {
    cursor = '' // 游标作废 → since 空 = snapshot
    clearLocal()
  }
  let since = full ? '' : cursor
  for (let i = 0; i < MAX_PAGES_PER_SYNC; i++) {
    // 快照一次拉足（limit 用服务端上限）；增量按 500 分批，hasMore 用 serverTime 续拉
    const page = await syncStockMarket(targetCid, since, full ? SNAPSHOT_LIMIT : SYNC_LIMIT)
    if (targetCid !== boundCid) return // 比赛已切换：丢弃过期响应
    applyPage(page)
    if (page.serverTime) {
      cursor = page.serverTime // 游标永远用上一响应的 serverTime
      lastSyncAt.value = page.serverTime
    }
    if (!page.hasMore) break
    since = cursor
  }
}

/** 一轮同步（带失败自动回退 snapshot） */
async function runSync(full: boolean): Promise<void> {
  syncing.value = true
  lastError.value = ''
  try {
    try {
      await syncOnce(full)
    } catch (e) {
      if (full) throw e
      // 增量失败（游标过期/异常）：游标作废，自动回退 snapshot 重试一次
      cursor = ''
      await syncOnce(true)
    }
  } catch (e) {
    // 404 = 比赛不存在/已删除（旧页面残留）：终止同步，避免无限重试风暴
    if (e instanceof ApiError && e.status === 404) {
      missing.value = true
      lastError.value = errorMessage(e, '比赛不存在或已删除')
      stop()
      throw e
    }
    lastError.value = errorMessage(e, '同步失败')
    throw e
  } finally {
    syncing.value = false
  }
}

/**
 * 立即同步一次。
 * in-flight 去重：上一次未返回不发新请求，本次请求合并进当前批次，
 * 待其返回后再补一轮（保证信号不丢且不产生并发 /stock/sync）。
 * @param full true = 强制快照重拉（清空本地重新 snapshot 起步）
 */
function syncNow(full = false): Promise<void> {
  if (full) fullPending = true
  if (inflight) {
    rerunPending = true
    return inflight
  }
  inflight = (async () => {
    do {
      const wantFull = fullPending
      fullPending = false
      rerunPending = false
      await runSync(wantFull)
    } while (rerunPending || fullPending)
  })().finally(() => {
    inflight = null
  })
  return inflight
}

/**
 * 去抖调度：窗口内多个 WS 信号/轮询合并成一次 /stock/sync；
 * 首个信号起设最大等待（2 个窗口），防止连续信号把同步无限推迟。
 */
function scheduleSync(): void {
  const now = Date.now()
  if (!firstPendingAt) firstPendingAt = now
  const windowMs = isHidden() ? HIDDEN_DEBOUNCE_MS : DEBOUNCE_MS
  const deadline = firstPendingAt + windowMs * 2
  const delay = Math.min(windowMs, Math.max(0, deadline - now))
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(firePendingSync, delay)
}

function firePendingSync(): void {
  debounceTimer = null
  firstPendingAt = 0
  // 后台自动同步失败不弹提示（原因记录在 lastError），避免信号风暴下的提示风暴
  void syncNow(false).catch(() => undefined)
}

function isHidden(): boolean {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden'
}

/** 页面可见性变化：隐藏退避到 10s 窗口；重新可见立即补一次 */
function onVisibilityChange(): void {
  if (isHidden()) {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
      debounceTimer = null
      scheduleSync() // 重新按 10s 退避窗口排期
    }
    return
  }
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
    firstPendingAt = 0
    void syncNow(false).catch(() => undefined)
  }
}

// ---------- 通道生命周期（引用计数：行情/交易两页共享） ----------

function startChannel(): void {
  refCount += 1
  if (refCount === 1 && typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }
}

function stopChannel(): void {
  if (refCount > 0) refCount -= 1
  if (refCount > 0) return
  if (debounceTimer) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  firstPendingAt = 0
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
  // 数据与游标保留：下次进入可直接走 delta，不拉全量
}

// ---------- 本地乐观更新（下单/撤单后立即并入本地，增量同步负责校正） ----------

function applyLocalOrder(order: StockOrder): void {
  if (!order || typeof order.id !== 'number') return
  orderById.set(orderKey(order), order)
  publish()
}

/** 撤销本地乐观行（下单失败回滚 / 服务端返回后移除占位行） */
function removeLocalOrder(id: number): void {
  if (orderById.delete(id)) publish()
}

function applyLocalHolding(holding: StockHolding): void {
  if (!holding) return
  holdingById.set(holdingKey(holding), holding)
  publish()
}

function applyLocalAccount(account: StockFundsAccount): void {
  if (!account) return
  accountById.set(accountKey(account), account)
  publish()
}

/**
 * 股票同步客户端（按比赛绑定；行情/交易两页共享同一条同步通道）。
 *
 * 使用方式：组件 setup 中 `const sync = useStockSync(() => props.cid)`，
 * onMounted 里 `sync.start()` + `sync.syncNow()`，onBeforeUnmount 里 `sync.stop()`；
 * 收到 WS `stock-updated` 信号时调用 `sync.scheduleSync()`（去抖合并）。
 */
export function useStockSync(cid: MaybeRefOrGetter<string | number | undefined>) {
  function bind(): void {
    switchCid(String(toValue(cid) ?? ''))
  }

  return {
    // ---------- 响应式数据 ----------
    /** 股票薄字段列表（全量在本地，视图按 50/页切片渲染） */
    stocks,
    /** K 线（按股票+轮次幂等覆盖） */
    candles,
    /** 我的委托 */
    orders,
    /** 我的持仓 */
    holdings,
    /** 我的资金账户 */
    accounts,
    /** 当前轮次 */
    round,
    /** 同步进行中 */
    syncing,
    /** 上次同步时间（= 下次增量游标） */
    lastSyncAt,
    /** 最近一次同步失败原因 */
    lastError,
    missing,

    // ---------- 控制 ----------
    /** 立即同步一次（full=true 强制快照重拉；带 in-flight 去重） */
    syncNow(full = false): Promise<void> {
      bind()
      return syncNow(full)
    },
    /** 去抖合并的增量同步（WS 信号/轮询入口） */
    scheduleSync(): void {
      bind()
      scheduleSync()
    },
    /** 启动同步通道（引用计数；首次启动注册可见性监听） */
    start(): void {
      bind()
      startChannel()
    },
    /** 停止同步通道（最后一次停止时清定时器/监听；数据与游标保留） */
    stop(): void {
      stopChannel()
    },

    // ---------- 本地乐观更新 ----------
    applyLocalOrder,
    removeLocalOrder,
    applyLocalHolding,
    applyLocalAccount,
  }
}

export type StockSync = ReturnType<typeof useStockSync>
