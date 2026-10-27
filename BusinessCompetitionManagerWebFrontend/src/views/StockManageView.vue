<script setup lang="ts">
// 交易管理：数据走 useStockSync 快照+增量；下单/撤单先本地乐观更新，再由增量校正。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { cancelStockOrder, placeStockOrder } from '@/api'
import type { StockOrder, StockOrderSide, StockOrderStatus } from '@/api/types'
import { useStockSync } from '@/composables/useStockSync'
import { useCountUp } from '@/composables/useMotion'
import { useNotifications, useResourceRefresh } from '@/composables/useNotifications'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()

const {
  stocks,
  orders,
  holdings,
  accounts,
  round,
  syncing,
  lastSyncAt,
  lastError,
  missing,
  syncNow,
  scheduleSync,
  start,
  stop,
  applyLocalOrder,
  removeLocalOrder,
} = useStockSync(() => props.cid)

// 轮次 0 是合法值（未推进过），只有「还没同步成功」才算未知——否则 0 会被显示成「—」
const roundReady = computed(() => round.value > 0 || lastSyncAt.value !== null)

// WS 信号只当触发器，去抖合并成一次增量同步，防请求风暴
useNotifications((message) => {
  if (message.payload?.type === 'stock-updated' || message.type === 'stock-updated') {
    scheduleSync()
  }
})

// Decimal 出站可能是字符串，统一转数字
function num(v: number | string | null | undefined): number {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? n : 0
}

function fmtMoney(v: number | string | null | undefined): string {
  return num(v).toFixed(2)
}

const priceByCode = computed<Map<string, number>>(() => {
  const map = new Map<string, number>()
  for (const s of stocks.value) map.set(String(s.code), num(s.currentPrice))
  return map
})

const SIDE_LABELS: Record<StockOrderSide, string> = { BUY: '买入', SELL: '卖出' }

function sideLabel(side: string): string {
  return SIDE_LABELS[side as StockOrderSide] ?? side
}
const STATUS_META: Record<StockOrderStatus, { label: string; type: 'success' | 'warning' | 'info' }> = {
  PENDING: { label: '挂单', type: 'warning' },
  FILLED: { label: '已成', type: 'success' },
  CANCELLED: { label: '已撤', type: 'info' },
}

function statusMeta(status: string): { label: string; type: 'success' | 'warning' | 'info' } {
  return STATUS_META[status as StockOrderStatus] ?? { label: status || '—', type: 'info' }
}

interface AccountView {
  id: number
  name: string
  ownerLabel: string
  bound: boolean
  cashBalance: number
  marketValue: number
  totalAssets: number
}

const accountViews = computed<AccountView[]>(() =>
  accounts.value.map((a) => {
    let marketValue = 0
    for (const h of holdings.value) {
      if (h.fundsAccountId === a.id) {
        marketValue += num(h.shares) * (priceByCode.value.get(String(h.stockCode)) ?? 0)
      }
    }
    // 绑定产业字段的账户以 fieldBalance 为准
    const cashBalance = num(a.fieldBalance ?? a.cashBalance)
    return {
      id: a.id,
      name: a.name,
      ownerLabel: a.ownerType === 'USER' ? '个人' : '公司',
      bound: Boolean(a.bindFieldId),
      cashBalance,
      marketValue,
      totalAssets: cashBalance + marketValue,
    }
  }),
)

// 账户合计只作展示，不参与下单/校验
const accountTotals = computed(() => {
  let cash = 0
  let marketValue = 0
  for (const a of accountViews.value) {
    cash += a.cashBalance
    marketValue += a.marketValue
  }
  return { cash, marketValue, total: cash + marketValue }
})

const cashShown = useCountUp(computed(() => accountTotals.value.cash), { precision: 2 })
const marketShown = useCountUp(computed(() => accountTotals.value.marketValue), {
  precision: 2,
})
const totalShown = useCountUp(computed(() => accountTotals.value.total), { precision: 2 })

// 无游标且无失败记录时显示骨架屏
const initialLoading = computed(() => !lastSyncAt.value && !lastError.value)

const accountsInitialLoading = computed(() => initialLoading.value && accounts.value.length === 0)

const PAGE_SIZE = 50
const holdingPage = ref(1)

interface HoldingView {
  id: number
  fundsAccountId: number
  stockCode: string
  stockName: string
  shares: number
  costPrice: number
  currentPrice: number
  marketValue: number
  profit: number
}

const holdingViews = computed<HoldingView[]>(() =>
  holdings.value.map((h) => {
    const shares = num(h.shares)
    const costPrice = num(h.costPrice)
    const currentPrice = priceByCode.value.get(String(h.stockCode)) ?? 0
    return {
      id: h.id,
      fundsAccountId: h.fundsAccountId,
      stockCode: String(h.stockCode),
      stockName: h.stockName || String(h.stockCode),
      shares,
      costPrice,
      currentPrice,
      marketValue: shares * currentPrice,
      profit: shares * (currentPrice - costPrice),
    }
  }),
)

const pagedHoldings = computed<HoldingView[]>(() =>
  holdingViews.value.slice((holdingPage.value - 1) * PAGE_SIZE, holdingPage.value * PAGE_SIZE),
)

watch(
  () => holdingViews.value.length,
  (total) => {
    const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE))
    if (holdingPage.value > maxPage) holdingPage.value = maxPage
  },
)

const orderPage = ref(1)
const statusFilter = ref('')

const filteredOrders = computed<StockOrder[]>(() => {
  if (!statusFilter.value) return orders.value
  return orders.value.filter((o) => o.status === statusFilter.value)
})

const pagedOrders = computed<StockOrder[]>(() =>
  filteredOrders.value.slice((orderPage.value - 1) * PAGE_SIZE, orderPage.value * PAGE_SIZE),
)

watch(statusFilter, () => {
  orderPage.value = 1
})

watch(
  () => filteredOrders.value.length,
  (total) => {
    const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE))
    if (orderPage.value > maxPage) orderPage.value = maxPage
  },
)

const form = reactive({
  code: '',
  side: 'BUY' as StockOrderSide,
  price: 0,
  quantity: 100,
})

// 上千股票用虚拟滚动下拉，避免一次性渲染卡顿
const stockOptions = computed(() =>
  stocks.value.map((s) => ({ label: `${s.code}  ${s.name}`, value: String(s.code) })),
)

watch(
  () => form.code,
  (code) => {
    const price = priceByCode.value.get(code)
    if (price !== undefined && price > 0) form.price = Number(price.toFixed(2))
  },
)

// 仅预览，实际以服务端撮合为准
const estAmount = computed(() => num(form.price) * num(form.quantity))

const sellableShares = computed(() => {
  if (!form.code) return 0
  return holdings.value
    .filter((h) => String(h.stockCode) === form.code)
    .reduce((sum, h) => sum + num(h.shares), 0)
})

const canSubmit = computed(
  () => Boolean(form.code) && num(form.price) > 0 && num(form.quantity) > 0 && !placing.value,
)

const placing = ref(false)

async function submitOrder(): Promise<void> {
  if (!form.code) {
    ElMessage.error('请选择股票')
    return
  }
  if (num(form.price) <= 0) {
    ElMessage.error('请输入委托价格')
    return
  }
  if (num(form.quantity) <= 0) {
    ElMessage.error('请输入委托数量')
    return
  }

  const code = form.code
  const stock = stocks.value.find((s) => String(s.code) === code)
  const now = new Date().toISOString()
  const tempId = -Date.now()

  // 先插乐观占位行，下单后立即可见
  applyLocalOrder({
    id: tempId,
    stockId: stock?.id ?? 0,
    stockCode: code,
    stockName: stock?.name ?? code,
    fundsAccountId: 0,
    side: form.side,
    price: num(form.price),
    quantity: num(form.quantity),
    amount: estAmount.value,
    status: 'PENDING',
    round: round.value,
    createdAt: now,
    updatedAt: now,
  })

  placing.value = true
  try {
    const created = await placeStockOrder(props.cid, {
      code,
      side: form.side,
      price: form.price,
      quantity: form.quantity,
    })
    // 用服务端返回替换占位行，后续增量校正
    removeLocalOrder(tempId)
    if (created && typeof created.id === 'number') applyLocalOrder(created)
    ElMessage.success('委托已提交，将在下一轮撮合')
    scheduleSync()
  } catch (e) {
    removeLocalOrder(tempId)
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    placing.value = false
  }
}

const cancellingId = ref(0)

async function onCancelOrder(row: StockOrder): Promise<void> {
  if (!row || row.status !== 'PENDING') return
  const previous: StockOrder = { ...row }
  applyLocalOrder({ ...row, status: 'CANCELLED', updatedAt: new Date().toISOString() })
  cancellingId.value = row.id
  try {
    const updated = await cancelStockOrder(props.cid, row.id)
    // 后端只回 id/status，并入现有行后由增量校正
    if (updated && typeof updated.id === 'number') {
      applyLocalOrder({
        ...row,
        status: updated.status ?? 'CANCELLED',
        updatedAt: new Date().toISOString(),
      })
    }
    ElMessage.success('已撤单')
    scheduleSync()
  } catch (e) {
    applyLocalOrder(previous)
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    cancellingId.value = 0
  }
}

async function manualSync(): Promise<void> {
  try {
    await syncNow(false)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

// 股票变更后增量重拉，保留分页/筛选
useResourceRefresh(['stock'], manualSync)

onMounted(() => {
  start()
  // 无游标走快照起步，有游标走增量
  void syncNow(false).catch((e) => {
    ElMessage.error(errorMessage(e, '操作失败'))
  })
})

onBeforeUnmount(() => {
  stop()
})

watch(
  () => props.cid,
  () => {
    holdingPage.value = 1
    orderPage.value = 1
    statusFilter.value = ''
    form.code = ''
    void syncNow(false).catch((e) => {
      ElMessage.error(errorMessage(e, '操作失败'))
    })
  },
)
</script>

<template>
  <div class="stock-manage-page">
    <el-alert
      v-if="missing"
      type="warning"
      show-icon
      :closable="false"
      title="比赛不存在或已删除"
      description="请返回比赛列表重新选择"
      class="missing-alert"
    >
      <template #default>
        <el-button type="primary" size="small" @click="$router.push('/competitions')">
          返回比赛列表
        </el-button>
      </template>
    </el-alert>

    <!-- 同步失败就地提示，不弹 toast，避免提示风暴 -->
    <el-alert
      v-if="lastError && !missing"
      type="error"
      show-icon
      :closable="false"
      :title="lastError"
      class="sync-error"
    />

    <div class="mm-toolbar">
      <h2 class="mm-title">交易管理</h2>
      <div class="mm-actions">
        <el-tag type="info" effect="plain">轮次：{{ roundReady ? round : '—' }}</el-tag>
        <el-tag v-if="lastSyncAt" type="success" effect="plain">
          同步于 {{ formatDateTime(lastSyncAt) }}
        </el-tag>
        <el-button :loading="syncing" @click="manualSync">
          <el-icon><Refresh /></el-icon>
          <span>同步</span>
        </el-button>
      </div>
    </div>

    <el-card shadow="never" class="block-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <span class="card-title">我的资金账户</span>
          <span class="card-sub">现金 + 持仓市值 = 总资产</span>
        </div>
      </template>
      <div v-if="accountViews.length" class="metric-grid account-summary">
        <div class="metric-card">
          <span class="metric-label">现金余额合计</span>
          <div class="metric-value">
            {{ cashShown.toFixed(2) }}<span class="metric-unit">元</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-label">持仓市值合计</span>
          <div class="metric-value">
            {{ marketShown.toFixed(2) }}<span class="metric-unit">元</span>
          </div>
        </div>
        <div class="metric-card">
          <span class="metric-label">总资产合计</span>
          <div class="metric-value">
            {{ totalShown.toFixed(2) }}<span class="metric-unit">元</span>
          </div>
        </div>
      </div>

      <div v-if="accountsInitialLoading" class="account-grid">
        <div v-for="i in 2" :key="i" class="skeleton account-skeleton" />
      </div>
      <div v-else-if="accountViews.length" class="account-grid">
        <div v-for="a in accountViews" :key="a.id" class="account-card">
          <div class="account-name">
            {{ a.name }}
            <el-tag size="small" effect="plain">{{ a.ownerLabel }}</el-tag>
            <el-tag v-if="a.bound" size="small" type="success" effect="plain">字段联动</el-tag>
          </div>
          <div class="account-stats">
            <div class="account-stat">
              <span>现金余额（元）</span>
              <b class="value-num">{{ fmtMoney(a.cashBalance) }}</b>
            </div>
            <div class="account-stat">
              <span>持仓市值（元）</span>
              <b class="value-num">{{ fmtMoney(a.marketValue) }}</b>
            </div>
            <div class="account-stat">
              <span>总资产（元）</span>
              <b class="total value-num">{{ fmtMoney(a.totalAssets) }}</b>
            </div>
          </div>
        </div>
      </div>
      <el-empty v-else description="暂无资金账户" :image-size="60" />
    </el-card>

    <div class="manage-grid">
      <el-card shadow="never" class="block-card order-card anim-fade-in-up">
        <template #header>
          <span class="card-title">下单</span>
        </template>
        <el-form label-position="top" class="order-form">
          <el-form-item label="股票" required>
            <el-select-v2
              v-model="form.code"
              :options="stockOptions"
              filterable
              clearable
              placeholder="选择股票（可输入代码/名称搜索）"
              style="width: 100%"
            />
          </el-form-item>

          <el-form-item label="方向" required>
            <el-radio-group v-model="form.side">
              <el-radio-button value="BUY">买入</el-radio-button>
              <el-radio-button value="SELL">卖出</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="委托价（元/股）" required>
            <el-input-number
              v-model="form.price"
              :min="0.01"
              :precision="2"
              :step="0.01"
              :controls="false"
              style="width: 100%"
            />
          </el-form-item>

          <el-form-item label="数量（股）" required>
            <el-input-number
              v-model="form.quantity"
              :min="1"
              :precision="0"
              :step="100"
              :controls="false"
              style="width: 100%"
            />
          </el-form-item>

          <div class="est-line">
            预计金额：<b class="value-num">{{ fmtMoney(estAmount) }}</b> 元
            <span v-if="form.side === 'SELL'" class="muted">
              （可卖 <span class="value-num">{{ sellableShares }}</span> 股）
            </span>
          </div>

          <el-button
            class="trade-submit"
            :class="form.side === 'BUY' ? 'is-buy' : 'is-sell'"
            style="width: 100%; height: 38px; font-size: 14px"
            :disabled="!canSubmit"
            :loading="placing"
            @click="submitOrder"
          >
            {{ form.side === 'BUY' ? '买入' : '卖出' }}
          </el-button>
        </el-form>
      </el-card>

      <el-card shadow="never" class="block-card anim-fade-in-up">
        <template #header>
          <div class="card-head">
            <span class="card-title">我的持仓</span>
            <span class="card-sub">共 {{ holdingViews.length }} 条</span>
          </div>
        </template>
        <div v-if="initialLoading" class="table-skeleton">
          <div v-for="i in 5" :key="i" class="skeleton skeleton-line" />
        </div>
        <el-table v-else :data="pagedHoldings" border stripe style="width: 100%">
          <template #empty>
            <el-empty description="暂无持仓" :image-size="60" />
          </template>
          <el-table-column prop="stockCode" label="代码" width="100" />
          <el-table-column prop="stockName" label="名称" min-width="120" />
          <el-table-column label="股数" width="110" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ row.shares }}</span>
            </template>
          </el-table-column>
          <el-table-column label="成本价（元）" width="120" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ fmtMoney(row.costPrice) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="现价（元）" width="110" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ fmtMoney(row.currentPrice) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="市值（元）" width="130" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ fmtMoney(row.marketValue) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="浮动盈亏（元）" width="140" align="right">
            <template #default="{ row }">
              <span class="value-num" :class="row.profit >= 0 ? 'up' : 'down'">
                {{ fmtMoney(row.profit) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination
            v-model:current-page="holdingPage"
            background
            layout="total, prev, pager, next"
            :page-size="PAGE_SIZE"
            :total="holdingViews.length"
          />
        </div>
      </el-card>
    </div>

    <el-card shadow="never" class="block-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <span class="card-title">我的委托</span>
          <div class="card-actions">
            <el-select
              v-model="statusFilter"
              clearable
              placeholder="按状态筛选"
              style="width: 150px"
            >
              <el-option label="挂单" value="PENDING" />
              <el-option label="已成" value="FILLED" />
              <el-option label="已撤" value="CANCELLED" />
            </el-select>
            <span class="card-sub">共 {{ filteredOrders.length }} 条</span>
          </div>
        </div>
      </template>

      <div v-if="initialLoading" class="table-skeleton">
        <div v-for="i in 5" :key="i" class="skeleton skeleton-line" />
      </div>
      <el-table v-else :data="pagedOrders" border stripe style="width: 100%">
        <template #empty>
          <el-empty description="暂无委托" :image-size="60" />
        </template>
        <el-table-column label="代码" width="100">
          <template #default="{ row }">{{ row.stockCode }}</template>
        </el-table-column>
        <el-table-column label="名称" min-width="120">
          <template #default="{ row }">{{ row.stockName || row.stockCode }}</template>
        </el-table-column>
        <el-table-column label="方向" width="80" align="center">
          <template #default="{ row }">
            <span :class="row.side === 'BUY' ? 'up' : 'down'">
              {{ sideLabel(row.side) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="委托价（元）" width="120" align="right">
          <template #default="{ row }">
            <span class="value-num">{{ fmtMoney(row.price) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="数量（股）" width="110" align="right">
          <template #default="{ row }">
            <span class="value-num">{{ num(row.quantity) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type" size="small">
              {{ statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="轮次" width="80" align="center">
          <template #default="{ row }">{{ row.round ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="委托时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'PENDING'"
              type="danger"
              size="small"
              text
              :loading="cancellingId === row.id"
              @click="onCancelOrder(row)"
            >
              撤单
            </el-button>
            <span v-else class="num-empty">—</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="orderPage"
          background
          layout="total, prev, pager, next"
          :page-size="PAGE_SIZE"
          :total="filteredOrders.length"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.mm-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 700;
  font-size: 15px;
}
.card-sub {
  font-size: var(--font-sm);
  color: var(--color-text-tertiary);
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.block-card {
  margin-bottom: 16px;
}
.sync-error {
  margin-bottom: 16px;
}

.account-summary {
  margin-bottom: 16px;
}
.account-skeleton {
  height: 118px;
  border-radius: var(--radius-sm);
}
.account-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.account-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  padding: 14px 16px;
}
.account-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 10px;
}
.account-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.account-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.account-stat span {
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.account-stat b {
  font-size: 15px;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.account-stat b.total {
  color: var(--color-primary);
}

.manage-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
/* 下单区吸附，滚动看持仓时入口不跳 */
@media (min-width: 1101px) {
  .order-card {
    position: sticky;
    top: 12px;
  }
}
.order-form {
  margin-top: 4px;
}
.est-line {
  font-size: 14px;
  margin-bottom: 14px;
  color: var(--color-text-secondary);
}
.est-line b {
  color: var(--color-primary);
  font-variant-numeric: tabular-nums;
}
.muted {
  color: var(--color-text-tertiary);
  font-size: 12px;
}
.form-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--color-text-tertiary);
  line-height: 1.6;
}

/* 红涨绿跌（中国股票惯例） */
.up {
  color: var(--color-danger);
  font-weight: 600;
}
.down {
  color: var(--color-success);
  font-weight: 600;
}
.num-empty {
  color: var(--color-text-tertiary);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.table-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
.table-skeleton .skeleton-line {
  height: 38px;
  margin-bottom: 0;
}
.table-skeleton .skeleton-line:last-child {
  width: 100%;
}

.el-button.trade-submit.is-buy {
  background-color: #ec0000 !important;
  border-color: #ec0000 !important;
  color: #fff !important;
}
.el-button.trade-submit.is-buy:hover {
  background-color: #d40000 !important;
  border-color: #d40000 !important;
}
.el-button.trade-submit.is-sell {
  background-color: #00a800 !important;
  border-color: #00a800 !important;
  color: #fff !important;
}
.el-button.trade-submit.is-sell:hover {
  background-color: #009000 !important;
  border-color: #009000 !important;
}
.el-button.trade-submit.is-buy:disabled,
.el-button.trade-submit.is-sell:disabled {
  opacity: 0.5;
}

@media (max-width: 1100px) {
  .manage-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 640px) {
  .account-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
