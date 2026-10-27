// 股票同步客户端（契约 docs/股票模块与同步优化.md §4.2/§5）
// snapshot 起步（since 传空）→ delta 游标合并：游标永远用上一响应的 serverTime（规避客户端时钟偏差），按 code/id 幂等覆盖。
// in-flight 去重；去抖 1.5s（首个信号起设最大等待）；页面隐藏退避 10s；增量失败自动回退 snapshot 重试一次。
// 性能红线：大列表一律 shallowRef 整体替换数组（不做逐项响应式代理），视图按 50/页切片，只走 /stock/sync。
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

const DEBOUNCE_MS = 1500
const HIDDEN_DEBOUNCE_MS = 10_000
const SYNC_LIMIT = 500
/** 快照起步用服务端上限一次拉足，降低被 limit 截断的概率 */
const SNAPSHOT_LIMIT = 2000
/** hasMore 续拉的安全上限，防服务端异常导致死循环 */
const MAX_PAGES_PER_SYNC = 50

const stocks = shallowRef<Stock[]>([])
const candles = shallowRef<StockCandle[]>([])
const orders = shallowRef<StockOrder[]>([])
const holdings = shallowRef<StockHolding[]>([])
const accounts = shallowRef<StockFundsAccount[]>([])
const round = ref(0)
const lastSyncAt = ref('')
const syncing = ref(false)
/** 最近一次失败原因：后台自动同步静默记录，手动同步由调用方统一弹错 */
const lastError = ref('')
const missing = ref(false)

// 合并缓冲：先 Map 幂等覆盖，再整体发布为浅引用数组
const stockByCode = new Map<string, Stock>()
const candleByKey = new Map<string, StockCandle>()
const orderById = new Map<string | number, StockOrder>()
const holdingById = new Map<string | number, StockHolding>()
const accountById = new Map<string | number, StockFundsAccount>()

let cursor = ''
let boundCid = ''
let refCount = 0
let debounceTimer: ReturnType<typeof setTimeout> | null = null
let firstPendingAt = 0
let inflight: Promise<void> | null = null
let rerunPending = false
let fullPending = false

function orderKey(o: StockOrder): string | number {
  return typeof o.id === 'number' ? o.id : `${o.fundsAccountId}#${o.stockCode}#${o.createdAt}`
}

function holdingKey(h: StockHolding): string | number {
  return typeof h.id === 'number' ? h.id : `${h.fundsAccountId}#${h.stockCode}`
}

function accountKey(a: StockFundsAccount): string | number {
  return typeof a.id === 'number' ? a.id : `${a.ownerType}#${a.companyId ?? a.userId}`
}

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

function switchCid(next: string): void {
  if (!next || next === boundCid) return
  boundCid = next
  cursor = ''
  lastSyncAt.value = ''
  lastError.value = ''
  round.value = 0
  clearLocal()
}

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

/** 立即同步一次；in-flight 去重：本次并入当前批次、待其返回后补一轮（不并发 /stock/sync）；full=true 强制快照重拉 */
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

/** 去抖调度：窗口内信号合并成一次；首个信号起设最大等待（2 个窗口），防连续信号无限推迟 */
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

function applyLocalOrder(order: StockOrder): void {
  if (!order || typeof order.id !== 'number') return
  orderById.set(orderKey(order), order)
  publish()
}

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

/** 用法：setup 里 useStockSync(() => props.cid)；onMounted 调 start() + syncNow()，收到 WS stock-updated 调 scheduleSync()，onBeforeUnmount 调 stop() */
export function useStockSync(cid: MaybeRefOrGetter<string | number | undefined>) {
  function bind(): void {
    switchCid(String(toValue(cid) ?? ''))
  }

  return {
    stocks,
    candles,
    orders,
    holdings,
    accounts,
    round,
    syncing,
    lastSyncAt,
    lastError,
    missing,

    syncNow(full = false): Promise<void> {
      bind()
      return syncNow(full)
    },
    scheduleSync(): void {
      bind()
      scheduleSync()
    },
    start(): void {
      bind()
      startChannel()
    },
    stop(): void {
      stopChannel()
    },

    applyLocalOrder,
    removeLocalOrder,
    applyLocalHolding,
    applyLocalAccount,
  }
}

