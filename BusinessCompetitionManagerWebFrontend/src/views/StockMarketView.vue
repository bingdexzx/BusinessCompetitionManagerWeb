<script setup lang="ts">
// 行情看板：数据走 useStockSync 快照+增量，WS 信号只触发去抖增量，不轮询。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
// echarts 按需注册，避免全量打包
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { advanceStockRound, getStockCandles, getStockMarket } from '@/api'
import type { Stock, StockCandle, StockMarketOverview } from '@/api/types'
import { useStockSync } from '@/composables/useStockSync'
import { useCountUp, useFlash } from '@/composables/useMotion'
import { useNotifications, useResourceRefresh } from '@/composables/useNotifications'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { CHART_THEME } from '@/utils/chartTheme'

echarts.use([
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  AxisPointerComponent,
  CanvasRenderer,
])

const props = defineProps<{ cid: string }>()

const auth = useAuthStore()
// 推进轮次仅系统超级管理员/本比赛超级管理员
const canManage = computed(() => auth.isSuperuser)

const {
  stocks,
  round,
  syncing,
  lastSyncAt,
  lastError,
  missing,
  syncNow,
  scheduleSync,
  start,
  stop,
} = useStockSync(() => props.cid)

// WS 信号只当触发器，去抖合并成一次增量同步
useNotifications((message) => {
  if (message.payload?.type === 'stock-updated' || message.type === 'stock-updated') {
    scheduleSync()
  }
})

const market = ref<StockMarketOverview | null>(null)

async function loadMarket(): Promise<void> {
  try {
    market.value = await getStockMarket(props.cid)
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  }
}

// 股票/公司变更后重拉概览；股票表由同步信号驱动
useResourceRefresh(['stock', 'companies'], loadMarket)

watch(round, (value) => {
  if (market.value && value > 0) market.value = { ...market.value, round: value }
})

const PAGE_SIZE = 50
const page = ref(1)
const keyword = ref('')

const filteredStocks = computed<Stock[]>(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return stocks.value
  return stocks.value.filter(
    (s) => String(s.code).toLowerCase().includes(kw) || String(s.name).toLowerCase().includes(kw),
  )
})

// 只渲染当前页 50 行，不全量渲染
const pagedStocks = computed<Stock[]>(() =>
  filteredStocks.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)

watch(keyword, () => {
  page.value = 1
})

watch(
  () => filteredStocks.value.length,
  (total) => {
    const maxPage = Math.max(1, Math.ceil(total / PAGE_SIZE))
    if (page.value > maxPage) page.value = maxPage
  },
)

const loadingStocks = computed(() => syncing.value && stocks.value.length === 0)

const selectedCode = ref('')
const selectedStock = computed<Stock | null>(
  () => stocks.value.find((s) => s.code === selectedCode.value) ?? null,
)

const { flashing: quoteFlashing, flash: flashQuote } = useFlash()

const overviewRound = computed(() => round.value || market.value?.round || 0)
const roundShown = useCountUp(overviewRound, { precision: 0 })
// 轮次 0 是**合法值**（股票已发行但还没推进过），只有「概览未加载」才算未知；
// 之前用 `roundShown || '—'` 把 0 也当成未知，导致行情页一直显示「—」。
const roundReady = computed(() => market.value !== null || round.value > 0)
const stockCount = computed(() => market.value?.stockCount ?? stocks.value.length)
const stockCountShown = useCountUp(stockCount, { precision: 0 })
const noStocks = computed(
  () => !missing.value && !loadingStocks.value && stockCount.value === 0,
)

const selectedPrice = computed(() => num(selectedStock.value?.currentPrice))
const selectedPriceShown = useCountUp(selectedPrice, { precision: 2 })
watch(selectedPrice, () => flashQuote())

// K 线缓存：code -> (round -> candle)，按轮次增量去重
const candleCache = new Map<string, Map<number, StockCandle>>()
const loadingCandles = ref(false)
// 竞态保护：只认当前正在加载的股票
let loadingCode = ''

function selectStock(row: Stock): void {
  if (!row || !row.code || row.code === selectedCode.value) return
  selectedCode.value = row.code
  void loadCandles(row.code)
}

function rowClassName({ row }: { row: Stock }): string {
  return row.code === selectedCode.value ? 'is-selected' : ''
}

// Decimal 出站可能是字符串，统一转数字
function num(v: number | string | null | undefined): number {
  const n = Number(v ?? 0)
  return Number.isFinite(n) ? n : 0
}

function normalizeCandle(c: StockCandle): StockCandle | null {
  if (!c || typeof c.round !== 'number') return null
  return {
    ...c,
    open: num(c.open),
    high: num(c.high),
    low: num(c.low),
    close: num(c.close),
    changePct: num(c.changePct),
    volume: num(c.volume),
  }
}

// 首次拉全量，之后只拉 fromRound 后的新增轮次
async function loadCandles(code: string): Promise<void> {
  const cache = candleCache.get(code) ?? new Map<number, StockCandle>()
  candleCache.set(code, cache)
  const rounds = Array.from(cache.keys())
  const fromRound = rounds.length ? Math.max(...rounds) : undefined
  loadingCode = code
  loadingCandles.value = true
  try {
    const list = await getStockCandles(
      props.cid,
      code,
      fromRound !== undefined ? { fromRound, limit: 500 } : { limit: 500 },
    )
    for (const item of list) {
      const candle = normalizeCandle(item)
      if (candle) cache.set(candle.round, candle)
    }
    if (selectedCode.value === code) {
      await nextTick()
      renderChart()
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    if (loadingCode === code) loadingCandles.value = false
  }
}

// 同步后只补拉选中股的新增轮次
watch(lastSyncAt, () => {
  if (selectedCode.value) void loadCandles(selectedCode.value)
})

const chartRef = ref<HTMLElement | null>(null)
type EChartsInstance = ReturnType<typeof echarts.init>
let chart: EChartsInstance | null = null

function changeClass(v: number | string | null | undefined): string {
  const n = num(v)
  return n > 0 ? 'up' : n < 0 ? 'down' : ''
}

function fmtPrice(v: number | string | null | undefined): string {
  return num(v).toFixed(2)
}

function fmtPct(v: number | string | null | undefined): string {
  const n = num(v)
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}

function calcMA(rows: number[][], period: number): (number | null)[] {
  return rows.map((_, i) => {
    if (i < period - 1) return null
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) {
      const row = rows[j]
      sum += row ? (row[1] ?? 0) : 0 // [open, close, low, high] 的 close
    }
    return Number((sum / period).toFixed(2))
  })
}

interface AxisParam {
  axisValue: string
  seriesType?: string
  value?: number[]
}

function renderChart(): void {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  const cache = candleCache.get(selectedCode.value)
  const list = cache ? Array.from(cache.values()).sort((a, b) => a.round - b.round) : []

  const ohlc = list.map((c) => [num(c.open), num(c.close), num(c.low), num(c.high)])
  const roundLabels = list.map((c) => `R${c.round}`)
  const ma5 = calcMA(ohlc, 5)
  const ma10 = calcMA(ohlc, 10)
  const ma20 = calcMA(ohlc, 20)

  // 默认显示最近 30 根
  const total = list.length
  const maxVisible = 30
  const defaultStart = total > maxVisible ? Math.round((1 - maxVisible / total) * 100) : 0

  // 暗色主题配色（沿用旧系统行情图视觉）
  const bg = CHART_THEME.bg
  const gridColor = CHART_THEME.grid
  const textColor = CHART_THEME.axisText
  const upColor = CHART_THEME.up
  const downColor = CHART_THEME.down

  chart.setOption(
    {
      backgroundColor: bg,
      animation: false,
      grid: [
        { left: 60, right: 60, top: 30, bottom: 100 },
        { left: 60, right: 60, top: '82%', bottom: 28 },
      ],
      axisPointer: {
        link: [{ xAxisIndex: [0, 1] }],
        label: { backgroundColor: '#3a3a4e', color: '#fff', fontSize: 11 },
      },
      xAxis: [
        {
          type: 'category',
          data: roundLabels,
          gridIndex: 0,
          axisLine: { lineStyle: { color: gridColor } },
          axisTick: { lineStyle: { color: gridColor } },
          axisLabel: { color: textColor, fontSize: 11 },
          splitLine: { show: false },
        },
        {
          type: 'category',
          data: roundLabels,
          gridIndex: 1,
          axisLine: { lineStyle: { color: gridColor } },
          axisTick: { lineStyle: { color: gridColor } },
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          gridIndex: 0,
          position: 'right',
          axisLine: { lineStyle: { color: gridColor } },
          axisTick: { lineStyle: { color: gridColor } },
          axisLabel: {
            color: textColor,
            fontSize: 11,
            formatter: (v: number | string) => Number(v).toFixed(2),
          },
          splitLine: { lineStyle: { color: gridColor, type: 'dashed' } },
        },
        {
          scale: true,
          gridIndex: 1,
          position: 'right',
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { show: false },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        {
          type: 'inside',
          xAxisIndex: [0, 1],
          start: defaultStart,
          end: 100,
          minValueSpan: 5,
        },
        {
          type: 'slider',
          xAxisIndex: [0, 1],
          start: defaultStart,
          end: 100,
          height: 18,
          bottom: 6,
          borderColor: 'transparent',
          backgroundColor: '#16162a',
          fillerColor: 'rgba(100, 100, 180, 0.2)',
          handleStyle: { color: '#4a4a6a', borderColor: '#4a4a6a' },
          textStyle: { color: textColor, fontSize: 10 },
        },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross', lineStyle: { color: '#555', type: 'dashed' } },
        backgroundColor: 'rgba(30, 30, 50, 0.95)',
        borderColor: '#3a3a4e',
        textStyle: { color: '#e0e0e0', fontSize: 12 },
        formatter: (params: unknown): string => {
          const list2 = Array.isArray(params) ? (params as AxisParam[]) : [params as AxisParam]
          const it = list2.find((p) => p && p.seriesType === 'candlestick')
          if (!it || !it.value) return ''
          const v = it.value
          const o = num(v[0])
          const c = num(v[1])
          const l = num(v[2])
          const h = num(v[3])
          const isUp = c >= o
          const color = isUp ? upColor : downColor
          const chg = o !== 0 ? (((c - o) / o) * 100).toFixed(2) : '0.00'
          const row = (label: string, val: string, cls: string) =>
            `<div style="display:flex;justify-content:space-between;gap:16px;"><span style="color:${textColor}">${label}</span><span style="color:${cls}">${val}</span></div>`
          let html = `<div style="font-weight:600;margin-bottom:6px;color:#fff">${it.axisValue}</div>`
          html += row('开盘', `¥${fmtPrice(o)}`, color)
          html += row('收盘', `¥${fmtPrice(c)}`, color)
          html += row('最低', `¥${fmtPrice(l)}`, downColor)
          html += row('最高', `¥${fmtPrice(h)}`, upColor)
          html += row('涨跌', `${isUp ? '+' : ''}${chg}%`, color)
          const idx = roundLabels.indexOf(it.axisValue)
          const maText = (name: string, arr: (number | null)[], maColor: string) => {
            const val = idx >= 0 ? arr[idx] : null
            return val != null
              ? `<div style="color:${maColor};font-size:11px;">${name}: ¥${fmtPrice(val)}</div>`
              : ''
          }
          html += `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #3a3a4e;">`
          html += maText('MA5', ma5, '#f5a623')
          html += maText('MA10', ma10, '#4b83c1')
          html += maText('MA20', ma20, '#e5484d')
          html += `</div>`
          return html
        },
      },
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ohlc,
          itemStyle: {
            color: upColor,
            color0: downColor,
            borderColor: upColor,
            borderColor0: downColor,
            borderWidth: 1,
          },
          barMaxWidth: 20,
          barMinWidth: 8,
        },
        {
          name: 'MA5',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma5,
          showSymbol: false,
          lineStyle: { color: '#f5a623', width: 1 },
          smooth: true,
        },
        {
          name: 'MA10',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma10,
          showSymbol: false,
          lineStyle: { color: '#4b83c1', width: 1 },
          smooth: true,
        },
        {
          name: 'MA20',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: ma20,
          showSymbol: false,
          lineStyle: { color: '#e5484d', width: 1 },
          smooth: true,
        },
        {
          name: '成交量',
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: list.map((c) => ({
            value: num(c.volume),
            itemStyle: { color: num(c.close) >= num(c.open) ? upColor : downColor, opacity: 0.7 },
          })),
          barMaxWidth: 16,
          barMinWidth: 4,
        },
      ],
    },
    true,
  )
  chart.resize()
}

function onResize(): void {
  chart?.resize()
}

// 取消选中时销毁图表，避免挂在已移除的 DOM 上
watch(selectedStock, (value) => {
  if (!value && chart) {
    chart.dispose()
    chart = null
  }
})

async function manualSync(): Promise<void> {
  try {
    await syncNow(false)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

const advancing = ref(false)

async function onAdvanceRound(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定推进轮次？将撮合挂单、生成 K 线并推进股票轮次。',
      '推进轮次',
      { type: 'warning', confirmButtonText: '推进', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  advancing.value = true
  try {
    await advanceStockRound(props.cid)
    ElMessage.success('轮次已推进')
    await loadMarket()
    await syncNow(false)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    advancing.value = false
  }
}

onMounted(() => {
  start()
  window.addEventListener('resize', onResize)
  void loadMarket()
  // 无游标走快照起步，有游标走增量
  void syncNow(false).catch((e) => {
    ElMessage.error(errorMessage(e, '操作失败'))
  })
})

onBeforeUnmount(() => {
  stop()
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})

watch(
  () => props.cid,
  () => {
    page.value = 1
    selectedCode.value = ''
    candleCache.clear()
    void loadMarket()
    void syncNow(false).catch((e) => {
      ElMessage.error(errorMessage(e, '操作失败'))
    })
  },
)
</script>

<template>
  <div class="stock-market-page page">
    <el-alert
      v-if="missing"
      type="error"
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

    <PageHeader title="股票行情">
      <template #actions>
      <div class="mm-actions">
        <el-tag type="info" effect="plain">
          轮次：{{ roundReady ? overviewRound : '—' }}
        </el-tag>
        <el-button :loading="syncing" @click="manualSync">
          <el-icon><Refresh /></el-icon>
          <span>同步</span>
        </el-button>
        <el-button
          v-if="canManage"
          type="primary"
          :loading="advancing"
          :disabled="noStocks"
          :title="noStocks ? '尚未发行股票，无法推进轮次' : ''"
          @click="onAdvanceRound"
        >
          <el-icon><VideoPlay /></el-icon>
          <span>推进轮次</span>
        </el-button>
      </div>
      </template>
    </PageHeader>

    <div
      class="metric-grid overview-grid anim-fade-in-up"
      :class="{ 'metrics-loading': loadingStocks }"
    >
      <div class="metric-card">
        <span class="metric-label">当前轮次</span>
        <div class="metric-value">{{ roundReady ? roundShown : '—' }}</div>
      </div>
      <div class="metric-card">
        <span class="metric-label">股票数</span>
        <div class="metric-value">{{ stockCountShown }}</div>
      </div>
      <div class="metric-card">
        <span class="metric-label">更新时间</span>
        <div class="metric-value ov-time">{{ formatDateTime(market?.updatedAt || lastSyncAt) }}</div>
      </div>
      <div class="metric-card">
        <span class="metric-label">同步状态</span>
        <div class="metric-value ov-status">
          <el-tag v-if="syncing" size="small" type="primary" effect="plain">同步中</el-tag>
          <el-tag v-else-if="lastSyncAt" size="small" type="success" effect="plain">已同步</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">待同步</el-tag>
        </div>
      </div>
    </div>

    <el-card shadow="never" class="block-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <span class="card-title">股票列表</span>
          <el-input
            v-model="keyword"
            clearable
            placeholder="搜索代码 / 名称"
            class="stock-search"
          />
        </div>
      </template>

      <div v-if="loadingStocks" class="table-skeleton">
        <div v-for="i in 6" :key="i" class="skeleton skeleton-line" />
      </div>
      <el-table
        v-else
        :data="pagedStocks"
        border
        stripe
        highlight-current-row
        class="clickable-table"
        style="width: 100%"
        :row-class-name="rowClassName"
        @row-click="selectStock"
       size="small">
        <template #empty>
          <el-empty description="暂无股票数据"  :image-size="72" />
        </template>
        <el-table-column prop="code" label="代码" width="110" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="现价（元）" width="130" align="right">
          <template #default="{ row }">
            <span class="stock-price value-num">{{ fmtPrice(row.currentPrice) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="涨跌幅" width="110" align="right">
          <template #default="{ row }">
            <span class="chg value-num" :class="changeClass(row.changePct)">
              {{ fmtPct(row.changePct) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="round" label="轮次" width="80" align="center" />
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          background
          layout="total, prev, pager, next"
          :page-size="PAGE_SIZE"
          :total="filteredStocks.length"
        />
      </div>
    </el-card>

    <el-card shadow="never" class="block-card chart-card anim-fade-in-up" :body-style="{ padding: '0' }">
      <template #header>
        <div class="chart-header">
          <span class="card-title">K 线（按需加载）</span>
          <span v-if="selectedStock" class="chart-quote">
            <b>{{ selectedStock.name }}</b>
            <span class="chart-code">{{ selectedStock.code }}</span>
            <span
              class="chart-price value-num"
              :class="[changeClass(selectedStock.changePct), { 'flash-updated': quoteFlashing }]"
            >
              ¥{{ selectedPriceShown.toFixed(2) }}
            </span>
            <span class="chg value-num" :class="changeClass(selectedStock.changePct)">
              {{ fmtPct(selectedStock.changePct) }}
            </span>
          </span>
          <span class="chart-ma-legend">
            <span class="ma-tag ma5">MA5</span>
            <span class="ma-tag ma10">MA10</span>
            <span class="ma-tag ma20">MA20</span>
          </span>
        </div>
      </template>

      <template v-if="selectedStock">
        <div v-loading="loadingCandles" ref="chartRef" class="kline-chart"></div>
        <div class="chart-hint">滚轮缩放 · 拖拽平移</div>
      </template>
      <div v-else class="chart-empty">
        <el-icon :size="40" class="chart-empty-icon"><TrendCharts /></el-icon>
        <p class="chart-empty-text">点击上方股票行查看 K 线</p>
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
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.overview-grid {
  margin-bottom: 16px;
}
.sync-error {
  margin-bottom: 16px;
}
.ov-time {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.9;
  color: var(--color-text-secondary);
}
.ov-status {
  font-size: var(--font-sm);
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
.stock-search {
  width: 220px;
}

.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}
.clickable-table :deep(.el-table__row.is-selected) {
  background: var(--el-color-primary-light-9);
}

.stock-price {
  font-weight: 600;
  color: var(--color-text-primary);
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
.chg {
  font-weight: 600;
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

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

.chart-card {
  margin-top: 16px;
  overflow: hidden;
}
.chart-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.chart-quote {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.chart-code {
  color: var(--color-text-tertiary);
  font-size: 12px;
}
.chart-price {
  font-size: 16px;
  font-weight: 700;
  padding: 0 4px;
  border-radius: var(--radius-xs);
}
.chart-ma-legend {
  margin-left: auto;
  display: flex;
  gap: 10px;
}
.ma-tag {
  font-size: 11px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 3px;
}
.ma-tag.ma5 {
  color: #f5a623;
  background: rgba(245, 166, 35, 0.1);
}
.ma-tag.ma10 {
  color: #4b83c1;
  background: rgba(75, 131, 193, 0.1);
}
.ma-tag.ma20 {
  color: #e5484d;
  background: rgba(229, 72, 77, 0.1);
}
.kline-chart {
  height: 480px;
  width: 100%;
  cursor: crosshair;
}
.chart-hint {
  text-align: center;
  font-size: 11px;
  color: #6a6a7a;
  padding: 6px 0;
  background: #1a1a2e;
  user-select: none;
}
.chart-empty {
  height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: #1a1a2e;
  color: #8a8a9a;
}
.chart-empty-icon {
  opacity: 0.45;
}
.chart-empty-text {
  margin: 0;
  font-size: 14px;
}

@media (max-width: 640px) {
  .stock-search {
    width: 100%;
  }
  .kline-chart {
    height: 300px;
  }
}
</style>
