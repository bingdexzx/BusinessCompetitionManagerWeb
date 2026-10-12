<script setup lang="ts">
// 股票行情看板：市场概览 + 股票表（50/页）+ 选中股 K 线按需加载（echarts 蜡烛图）
// 数据全部走 useStockSync（快照+增量合并），WS stock-updated 信号只做去抖增量触发，不轮询。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
// echarts 按需引入（tree-shaking）：只装蜡烛图 + MA 线 + 成交量柱，避免全量打包
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
import { useNotifications } from '@/composables/useNotifications'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

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
/** 推进轮次仅比赛超管 / 系统超管（与后端权限口径一致） */
const canManage = computed(
  () => auth.isSuperuser || auth.currentMembership?.identity === 'COMP_SUPER_ADMIN',
)

// ---------- 同步通道（快照+增量，WS 信号去抖合并） ----------
const {
  stocks,
  round,
  syncing,
  lastSyncAt,
  missing,
  syncNow,
  scheduleSync,
  start,
  stop,
} = useStockSync(() => props.cid)

/** WS 推送信号只当触发器：合并成一次去抖增量同步（防请求风暴） */
useNotifications((message) => {
  // 信号契约 §4.3：{type:'stock-updated', round, serverTime}（不带数据）
  if (message.payload?.type === 'stock-updated' || message.type === 'stock-updated') {
    scheduleSync()
  }
})

// ---------- 市场概览（轻量心跳接口） ----------
const market = ref<StockMarketOverview | null>(null)

async function loadMarket(): Promise<void> {
  try {
    market.value = await getStockMarket(props.cid)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

// 同步响应里的轮次最新，概览轮次跟随同步实时刷新
watch(round, (value) => {
  if (market.value && value > 0) market.value = { ...market.value, round: value }
})

// ---------- 股票表（50/页，行点击选中） ----------
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

/** 只把当前页 50 行交给 el-table 渲染，绝不一次性渲染全量行 */
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

// ---------- 选中股 + K 线（按需加载，缓存按轮次 keyset 增量） ----------
const selectedCode = ref('')
const selectedStock = computed<Stock | null>(
  () => stocks.value.find((s) => s.code === selectedCode.value) ?? null,
)

/** K 线缓存：code -> (round -> candle)，增量合并去重 */
const candleCache = new Map<string, Map<number, StockCandle>>()
const loadingCandles = ref(false)
/** 竞态保护：只认当前正在加载的股票 */
let loadingCode = ''

function selectStock(row: Stock): void {
  if (!row || !row.code || row.code === selectedCode.value) return
  selectedCode.value = row.code
  void loadCandles(row.code)
}

/** 选中行高亮（el-table row-class-name） */
function rowClassName({ row }: { row: Stock }): string {
  return row.code === selectedCode.value ? 'is-selected' : ''
}

/** Decimal 出站可能是字符串，画图/计算前统一转数字 */
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

/** 按需加载 K 线：首次全量（limit 截断），之后只拉 fromRound 之后的新增轮次 */
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
      if (candle) cache.set(candle.round, candle) // 按轮次幂等覆盖
    }
    if (selectedCode.value === code) {
      await nextTick()
      renderChart()
    }
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    if (loadingCode === code) loadingCandles.value = false
  }
}

/** 同步命中新增 K 线后，只补拉选中股的新增轮次（keyset 增量，不拉全量） */
watch(lastSyncAt, () => {
  if (selectedCode.value) void loadCandles(selectedCode.value)
})

// ---------- echarts 蜡烛图（红涨绿跌 + MA5/10/20 + 成交量） ----------
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
  const bg = '#1a1a2e'
  const gridColor = '#2a2a3e'
  const textColor = '#8a8a9a'
  const upColor = '#ec0000'
  const downColor = '#00a800'

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

// 取消选中（如切换比赛）时销毁图表实例，避免挂在已移除的 DOM 上
watch(selectedStock, (value) => {
  if (!value && chart) {
    chart.dispose()
    chart = null
  }
})

// ---------- 手动同步 / 推进轮次 ----------
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
      '推进轮次将撮合挂单、生成 K 线并推进股票轮次，确认继续？',
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
    await syncNow(false) // 推进后立即增量同步校正（不拉全量）
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    advancing.value = false
  }
}

// ---------- 初始化 ----------
onMounted(() => {
  start()
  window.addEventListener('resize', onResize)
  void loadMarket()
  // 首次进入（无游标）自动快照起步；已有游标则一次增量
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
  <div class="stock-market-page">
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
      <h2 class="mm-title">股票行情</h2>
      <div class="mm-actions">
        <el-tag type="info" effect="plain">轮次：{{ round || market?.round || '—' }}</el-tag>
        <el-button :loading="syncing" @click="manualSync">
          <el-icon><Refresh /></el-icon>
          <span>同步</span>
        </el-button>
        <el-button
          v-if="canManage"
          type="warning"
          :loading="advancing"
          @click="onAdvanceRound"
        >
          <el-icon><VideoPlay /></el-icon>
          <span>推进轮次</span>
        </el-button>
      </div>
    </div>

    <!-- 市场概览（轮次 / 股票数 / 更新时间） -->
    <div class="market-overview anim-fade-in-up">
      <div class="ov-item">
        <span class="ov-label">当前轮次</span>
        <b class="ov-value">{{ round || market?.round || '—' }}</b>
      </div>
      <div class="ov-item">
        <span class="ov-label">股票数</span>
        <b class="ov-value">{{ market?.stockCount ?? stocks.length }}</b>
      </div>
      <div class="ov-item">
        <span class="ov-label">更新时间</span>
        <b class="ov-value ov-time">{{ formatDateTime(market?.updatedAt || lastSyncAt) }}</b>
      </div>
      <div class="ov-item">
        <span class="ov-label">同步状态</span>
        <b class="ov-value">
          <el-tag v-if="syncing" size="small" type="primary" effect="plain">同步中</el-tag>
          <el-tag v-else-if="lastSyncAt" size="small" type="success" effect="plain">已同步</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">待同步</el-tag>
        </b>
      </div>
    </div>

    <!-- 股票表：50/页，行点击选中后按需加载 K 线 -->
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

      <el-table
        v-loading="loadingStocks"
        :data="pagedStocks"
        border
        stripe
        highlight-current-row
        class="clickable-table"
        style="width: 100%"
        :row-class-name="rowClassName"
        @row-click="selectStock"
      >
        <template #empty>
          <el-empty description="暂无股票数据" />
        </template>
        <el-table-column prop="code" label="代码" width="110" />
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="现价（元）" width="130" align="right">
          <template #default="{ row }">
            <span class="stock-price">{{ fmtPrice(row.currentPrice) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="涨跌幅" width="110" align="right">
          <template #default="{ row }">
            <span class="chg" :class="changeClass(row.changePct)">{{ fmtPct(row.changePct) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="round" label="轮次" width="80" align="center" />
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.updatedAt) }}</template>
        </el-table-column>
      </el-table>

      <!-- 分页：每页 50 行，绝不一次性渲染全量 -->
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

    <!-- 选中股 K 线（按需加载） -->
    <el-card shadow="never" class="block-card chart-card anim-fade-in-up" :body-style="{ padding: '0' }">
      <template #header>
        <div class="chart-header">
          <span class="card-title">K 线（按需加载）</span>
          <span v-if="selectedStock" class="chart-quote">
            <b>{{ selectedStock.name }}</b>
            <span class="chart-code">{{ selectedStock.code }}</span>
            <span class="chart-price" :class="changeClass(selectedStock.changePct)">
              ¥{{ fmtPrice(selectedStock.currentPrice) }}
            </span>
            <span class="chg" :class="changeClass(selectedStock.changePct)">
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
        <div class="chart-hint">滚轮缩放 · 拖拽平移 · 底部滑块 · MA5/MA10/MA20</div>
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
  gap: 10px;
  flex-wrap: wrap;
}

/* ===== 市场概览 ===== */
.market-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.ov-item {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ov-label {
  font-size: var(--font-sm);
  color: var(--color-text-tertiary);
}
.ov-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
}
.ov-time {
  font-size: 15px;
  line-height: 1.8;
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
  font-variant-numeric: tabular-nums;
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
.chg {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}

/* ===== K 线卡片 ===== */
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
  font-variant-numeric: tabular-nums;
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

/* ===== 响应式 ===== */
@media (max-width: 1024px) {
  .market-overview {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
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
