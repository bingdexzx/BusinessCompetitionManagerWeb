<script setup lang="ts">
// 交易管理：资金账户 + 持仓表（分页）+ 委托列表（分页/状态筛选/撤单）+ 下单表单
// 数据全部走 useStockSync（快照+增量合并）；下单/撤单做本地乐观更新，随后增量校正，不拉全量。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { cancelStockOrder, placeStockOrder } from '@/api'
import type { StockOrder, StockOrderSide, StockOrderStatus } from '@/api/types'
import { useStockSync } from '@/composables/useStockSync'
import { useNotifications } from '@/composables/useNotifications'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()

// ---------- 同步通道（快照+增量，WS 信号去抖合并） ----------
const {
  stocks,
  orders,
  holdings,
  accounts,
  round,
  syncing,
  lastSyncAt,
  missing,
  syncNow,
  scheduleSync,
  start,
  stop,
  applyLocalOrder,
  removeLocalOrder,
} = useStockSync(() => props.cid)

/** WS 推送信号只当触发器：合并成一次去抖增量同步（防请求风暴） */
useNotifications((message) => {
  // 信号契约 §4.3：{type:'stock-updated', round, serverTime}（不带数据）
  if (message.payload?.type === 'stock-updated' || message.type === 'stock-updated') {
    scheduleSync()
  }
})

// ---------- 展示小工具 ----------
/** Decimal 出站可能是字符串，计算/展示前统一转数字 */
function num(v: number | string | null | undefined): number {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? n : 0
}

function fmtMoney(v: number | string | null | undefined): string {
  return num(v).toFixed(2)
}

/** 现价索引（按 code，持仓市值/盈亏、下单默认价使用） */
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

// ---------- 我的资金账户（信息卡：账户数少，不做大表） ----------
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
    // 绑定产业字段的账户以实时字段现金为准（fieldBalance）
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

// ---------- 持仓表（50/页） ----------
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

// ---------- 委托列表（50/页 + 状态筛选 + PENDING 撤单） ----------
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

// ---------- 下单表单（股票选择 / 方向 / 价格 / 数量） ----------
const form = reactive({
  code: '',
  side: 'BUY' as StockOrderSide,
  price: 0,
  quantity: 100,
})

/** 大列表下拉用虚拟滚动的 el-select-v2，避免上千股票一次性渲染卡顿 */
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

/** 预计金额（仅预览；实际以服务端精确撮合为准） */
const estAmount = computed(() => num(form.price) * num(form.quantity))

/** 卖出可用电量（选中股票的持仓股数） */
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

  // 本地乐观更新：先占位挂单行（下单后立即可见），不拉全量
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
    // 用服务端返回替换乐观占位行；后续增量同步负责校正（持仓/资金/订单），不拉全量
    removeLocalOrder(tempId)
    if (created && typeof created.id === 'number') applyLocalOrder(created)
    ElMessage.success('委托已提交，将在下一轮撮合')
    scheduleSync()
  } catch (e) {
    removeLocalOrder(tempId) // 失败回滚乐观行
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    placing.value = false
  }
}

// ---------- 撤单（PENDING 可撤，乐观置已撤 + 增量校正） ----------
const cancellingId = ref(0)

async function onCancelOrder(row: StockOrder): Promise<void> {
  if (!row || row.status !== 'PENDING') return
  const previous: StockOrder = { ...row }
  // 本地乐观更新：先置为已撤
  applyLocalOrder({ ...row, status: 'CANCELLED', updatedAt: new Date().toISOString() })
  cancellingId.value = row.id
  try {
    const updated = await cancelStockOrder(props.cid, row.id)
    // 后端只回 { id, status }：把权威状态并入现有行（随后增量同步校正），不拉全量
    if (updated && typeof updated.id === 'number') {
      applyLocalOrder({
        ...row,
        status: updated.status ?? 'CANCELLED',
        updatedAt: new Date().toISOString(),
      })
    }
    ElMessage.success('已撤单')
    scheduleSync() // 增量校正，不拉全量
  } catch (e) {
    applyLocalOrder(previous) // 失败回滚
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    cancellingId.value = 0
  }
}

// ---------- 手动同步 ----------
async function manualSync(): Promise<void> {
  try {
    await syncNow(false)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

// ---------- 初始化 ----------
onMounted(() => {
  start()
  // 首次进入（无游标）自动快照起步；已有游标则一次增量
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
    <!-- 比赛不存在/已删除（旧页面残留） -->
    <el-alert
      v-if="missing"
      type="warning"
      show-icon
      :closable="false"
      title="比赛不存在或已删除"
      description="当前页面指向的比赛已不存在（可能被清理/重建）。请返回比赛列表选择现有比赛。"
      class="missing-alert"
    >
      <template #default>
        <el-button type="primary" size="small" @click="$router.push('/competitions')">
          返回比赛列表
        </el-button>
      </template>
    </el-alert>

    <!-- 工具栏 -->
    <div class="mm-toolbar">
      <h2 class="mm-title">交易管理</h2>
      <div class="mm-actions">
        <el-tag type="info" effect="plain">轮次：{{ round || '—' }}</el-tag>
        <el-tag v-if="lastSyncAt" type="success" effect="plain">
          同步于 {{ formatDateTime(lastSyncAt) }}
        </el-tag>
        <el-button :loading="syncing" @click="manualSync">
          <el-icon><Refresh /></el-icon>
          <span>同步</span>
        </el-button>
      </div>
    </div>

    <!-- 我的资金账户（账户数少，信息卡展示；持仓大表走下方分页） -->
    <el-card shadow="never" class="block-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <span class="card-title">我的资金账户</span>
          <span class="card-sub">现金 + 持仓市值 = 总资产</span>
        </div>
      </template>
      <div v-if="accountViews.length" class="account-grid">
        <div v-for="a in accountViews" :key="a.id" class="account-card">
          <div class="account-name">
            {{ a.name }}
            <el-tag size="small" effect="plain">{{ a.ownerLabel }}</el-tag>
            <el-tag v-if="a.bound" size="small" type="success" effect="plain">字段联动</el-tag>
          </div>
          <div class="account-stats">
            <div class="account-stat">
              <span>现金余额（元）</span>
              <b>{{ fmtMoney(a.cashBalance) }}</b>
            </div>
            <div class="account-stat">
              <span>持仓市值（元）</span>
              <b>{{ fmtMoney(a.marketValue) }}</b>
            </div>
            <div class="account-stat">
              <span>总资产（元）</span>
              <b class="total">{{ fmtMoney(a.totalAssets) }}</b>
            </div>
          </div>
        </div>
      </div>
      <el-empty v-else description="暂无资金账户" :image-size="60" />
    </el-card>

    <div class="manage-grid">
      <!-- 下单表单 -->
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
            预计金额：<b>{{ fmtMoney(estAmount) }}</b> 元
            <span v-if="form.side === 'SELL'" class="muted">（可卖 {{ sellableShares }} 股）</span>
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
          <div class="form-hint">下单后本地立即入列，由增量同步校正持仓/资金，不拉全量。</div>
        </el-form>
      </el-card>

      <!-- 我的持仓（分页） -->
      <el-card shadow="never" class="block-card anim-fade-in-up">
        <template #header>
          <div class="card-head">
            <span class="card-title">我的持仓</span>
            <span class="card-sub">共 {{ holdingViews.length }} 条</span>
          </div>
        </template>
        <el-table :data="pagedHoldings" border stripe style="width: 100%">
          <template #empty>
            <el-empty description="暂无持仓" :image-size="60" />
          </template>
          <el-table-column prop="stockCode" label="代码" width="100" />
          <el-table-column prop="stockName" label="名称" min-width="120" />
          <el-table-column label="股数" width="110" align="right">
            <template #default="{ row }">{{ row.shares }}</template>
          </el-table-column>
          <el-table-column label="成本价（元）" width="120" align="right">
            <template #default="{ row }">{{ fmtMoney(row.costPrice) }}</template>
          </el-table-column>
          <el-table-column label="现价（元）" width="110" align="right">
            <template #default="{ row }">{{ fmtMoney(row.currentPrice) }}</template>
          </el-table-column>
          <el-table-column label="市值（元）" width="130" align="right">
            <template #default="{ row }">{{ fmtMoney(row.marketValue) }}</template>
          </el-table-column>
          <el-table-column label="浮动盈亏（元）" width="140" align="right">
            <template #default="{ row }">
              <span :class="row.profit >= 0 ? 'up' : 'down'">{{ fmtMoney(row.profit) }}</span>
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

    <!-- 我的委托（分页 + 状态筛选 + 撤单） -->
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

      <el-table :data="pagedOrders" border stripe style="width: 100%">
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
          <template #default="{ row }">{{ fmtMoney(row.price) }}</template>
        </el-table-column>
        <el-table-column label="数量（股）" width="110" align="right">
          <template #default="{ row }">{{ num(row.quantity) }}</template>
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

/* ===== 资金账户 ===== */
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

/* ===== 下单 + 持仓 两栏布局 ===== */
.manage-grid {
  display: grid;
  grid-template-columns: 360px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
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
  color: #f5483b;
  font-weight: 600;
}
.down {
  color: #16a34a;
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

/* 买卖按钮：红买绿卖 */
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

/* ===== 响应式 ===== */
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
