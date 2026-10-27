<template>
  <div class="dashboard">
    <div class="page-head">
      <div class="page-head-main">
        <h2 class="page-title">{{ layout?.title || '仪表盘' }}</h2>
      </div>
      <el-button @click="load">刷新</el-button>
    </div>

    <el-alert
      v-if="loadError"
      class="dashboard-error"
      type="error"
      :closable="false"
      show-icon
      :title="loadError"
    >
      <el-button size="small" @click="load">重新加载</el-button>
    </el-alert>

    <div v-if="!loaded" class="dash-skeleton">
      <div class="metric-grid">
        <div v-for="n in 4" :key="`sk-metric-${n}`" class="metric-card metric-skeleton">
          <div class="skeleton skeleton-line metric-skeleton-label"></div>
          <div class="skeleton metric-skeleton-value"></div>
        </div>
      </div>
      <div class="grid">
        <div v-for="n in 2" :key="`sk-panel-${n}`" class="panel comp-wide panel-skeleton">
          <div class="skeleton skeleton-line panel-skeleton-title"></div>
          <div class="skeleton skeleton-line"></div>
          <div class="skeleton skeleton-line"></div>
        </div>
      </div>
    </div>

    <template v-else>
      <el-empty
        v-if="!components.length && scopedCompanies.length === 0 && industryTabs.length <= 1"
        description="比赛包未提供仪表盘样式文件（dashboard.json）"
      />

      <template v-else>
        <el-tabs v-model="activeTab" class="industry-tabs">
          <el-tab-pane
            v-for="tab in industryTabs"
            :key="tab.key"
            :name="tab.key"
            :label="tab.label"
          />
        </el-tabs>

        <div v-if="activeTab !== '__all__'" class="scope-hint">
          当前产业：<b>{{ activeTabLabel }}</b>（{{ scopedCompanies.length }} 家公司参与统计）
          <template v-if="scopedCompanies.length">：
            <span v-for="c in scopedCompanies" :key="c.id" class="scope-chip">{{ c.name }}</span>
          </template>
        </div>

        <section v-for="section in sections" :key="section.key" class="dash-section">
          <div v-if="section.metrics.length" class="metric-grid anim-stagger">
            <div
              v-for="comp in section.metrics"
              :key="comp.id || comp.title"
              class="metric-card"
              :class="{ 'metric-card--gauge': comp.type === 'gauge' }"
            >
              <div class="metric-label">{{ comp.title }}</div>
              <div v-if="comp.type === 'gauge'" class="gauge-body">
                <div class="metric-value">
                  <MetricValue
                    :value="aggregate(comp)"
                    :precision="precisionOf(comp)"
                    :suffix="comp.suffix || ''"
                  />
                </div>
                <el-progress
                  class="metric-gauge"
                  type="dashboard"
                  :percentage="gaugePercent(comp)"
                  :stroke-width="8"
                  :width="92"
                />
              </div>
              <div v-else class="metric-value">
                <MetricValue
                  :value="aggregate(comp)"
                  :precision="precisionOf(comp)"
                  :suffix="comp.suffix || ''"
                />
              </div>
              <div v-if="comp.description" class="metric-note">{{ comp.description }}</div>
            </div>
          </div>

          <div v-if="section.panels.length" class="grid anim-stagger">
            <el-card
              v-for="comp in section.panels"
              :key="comp.id || comp.title"
              class="comp"
              :class="{ 'comp-wide': comp.type === 'table', 'comp-text': comp.type === 'text' }"
              shadow="never"
            >
              <div class="comp-title">{{ comp.title }}</div>
              <div v-if="comp.type === 'text'" class="text-body">{{ comp.text }}</div>
              <el-table v-else :data="tableRows(comp)" size="small" empty-text="暂无可操作公司">
                <el-table-column prop="company" label="公司" min-width="140" />
                <el-table-column prop="industry" label="产业" width="120" />
                <el-table-column label="数值" width="140" align="right">
                  <template #default="{ row }">
                    <span class="value-num">{{ row.value }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-card>
          </div>
        </section>

        <el-empty
          v-if="!components.length"
          description="该产业暂无专属布局，且比赛包未提供通用布局"
        />
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, ref, watch, type PropType } from 'vue'
import * as api from '@/api'
import { getDashboardLayout } from '@/api/dashboardApi'
import type { DashboardComponent, DashboardLayout } from '@/api/dashboardApi'
import type { Company, CompanyField, CompanyTable } from '@/api/types'
import { errorMessage } from '@/utils/errors'
import { ElMessage } from 'element-plus'
import { subscribeCompetition, useResourceRefresh } from '@/composables/useNotifications'
import { useCatalog } from '@/composables/useCatalog'
import { useCountUp, useFlash } from '@/composables/useMotion'

const props = defineProps<{ cid: string }>()

// 产业键 → 中文名（仪表盘布局未给 title 时用它兜底）
const catalog = useCatalog(() => props.cid)
const industryLabel = catalog.industryLabel

const layout = ref<DashboardLayout | null>(null)
const companies = ref<Company[]>([])
const tables = ref<Record<number, Record<string, CompanyTable>>>({})
const loaded = ref(false)
const activeTab = ref('__all__')
const loadError = ref('')

// dashboard.json 动态给组件，需按组件各建滚动/闪烁实例
const MetricValue = defineComponent({
  name: 'DashboardMetricValue',
  props: {
    value: { type: Number as PropType<number | null>, default: null },
    precision: { type: Number, default: 0 },
    suffix: { type: String, default: '' },
  },
  setup(props) {
    const shown = useCountUp(computed(() => props.value), {
      // 内部统一 2 位滚动，避免整数/小数切换时刻度不一致
      precision: 2,
    })
    const { flashing, flash } = useFlash(900)
    watch(
      () => props.value,
      (next, prev) => {
        // 首次填充不算实时更新，仅数值变化才闪
        if (typeof next === 'number' && typeof prev === 'number' && next !== prev) flash()
      },
    )
    return () => {
      const hasValue = typeof props.value === 'number' && Number.isFinite(props.value)
      return h(
        'span',
        { class: { 'flash-updated': flashing.value } },
        hasValue
          ? [
              shown.value.toFixed(props.precision),
              props.suffix ? h('span', { class: 'metric-unit' }, props.suffix) : null,
            ]
          : '—',
      )
    }
  },
})

const industryTabs = computed(() => {
  const seen = new Set<string>()
  const tabs: Array<{ key: string; label: string }> = [{ key: '__all__', label: '全部' }]
  const labelOf = (key: string): string =>
    layout.value?.industries?.[key]?.title || industryLabel(key)
  for (const company of companies.value) {
    const key = company.industryKey || ''
    if (!key || seen.has(key)) continue
    seen.add(key)
    tabs.push({ key, label: labelOf(key) })
  }
  for (const key of Object.keys(layout.value?.industries || {})) {
    if (seen.has(key)) continue
    seen.add(key)
    tabs.push({ key, label: labelOf(key) })
  }
  return tabs
})

const activeTabLabel = computed(
  () => industryTabs.value.find((t) => t.key === activeTab.value)?.label || activeTab.value,
)

const scopedCompanies = computed(() => {
  if (activeTab.value === '__all__') return companies.value
  return companies.value.filter((c) => (c.industryKey || '') === activeTab.value)
})

// 产业页签优先专属布局，缺失退化通用布局
const components = computed<DashboardComponent[]>(() => {
  const all = layout.value?.components || []
  if (activeTab.value === '__all__') return all
  const section = layout.value?.industries?.[activeTab.value]
  return section?.components?.length ? section.components : all
})

const topComponents = computed(() => components.value.filter((c) => (c.zone || 'top') === 'top'))
const bottomComponents = computed(() => components.value.filter((c) => c.zone === 'bottom'))

const sections = computed(() => {
  const isMetric = (comp: DashboardComponent): boolean =>
    comp.type === 'number' || comp.type === 'gauge'
  return [
    {
      key: 'top',
      metrics: topComponents.value.filter(isMetric),
      panels: topComponents.value.filter((comp) => !isMetric(comp)),
    },
    {
      key: 'bottom',
      metrics: bottomComponents.value.filter(isMetric),
      panels: bottomComponents.value.filter((comp) => !isMetric(comp)),
    },
  ].filter((section) => section.metrics.length > 0 || section.panels.length > 0)
})

// 最新财年值：财年表取最大数值键，实体表视为无财年
function newestValue(field: CompanyField | undefined): number | null {
  if (!field) return null
  const values = field.values || {}
  const keys = Object.keys(values)
  if (!keys.length) return null

  if (keys.length === 1) {
    const raw = Number(values[keys[0]!])
    return Number.isFinite(raw) ? raw : null
  }
  if (keys.includes('null') || keys.includes('')) {
    const raw = Number(values['null'] ?? values[''])
    return Number.isFinite(raw) ? raw : null
  }

  let newestKey = -Infinity
  let newestRaw: unknown = null
  for (const key of keys) {
    const num = Number(key)
    if (!Number.isFinite(num) || num <= newestKey) continue
    newestKey = num
    newestRaw = values[key]
  }
  if (newestKey === -Infinity) return null
  const raw = Number(newestRaw)
  return Number.isFinite(raw) ? raw : null
}

function fieldValue(table: CompanyTable | undefined, fieldKey: string): number | null {
  const field = table?.fields.find((f) => f.key === fieldKey)
  return newestValue(field)
}

function aggregate(comp: DashboardComponent): number | null {
  const bind = comp.bind
  if (!bind) return null
  const nums: number[] = []
  for (const company of scopedCompanies.value) {
    const table = tables.value[company.id]?.[bind.table]
    const value = fieldValue(table, bind.fieldKey)
    if (value !== null) nums.push(value)
  }
  if (!nums.length) return null
  switch (bind.aggregate || 'latest') {
    case 'sum':
      return nums.reduce((a, b) => a + b, 0)
    case 'average':
      return nums.reduce((a, b) => a + b, 0) / nums.length
    default:
      // latest 也按各公司最新值求和
      return nums.reduce((a, b) => a + b, 0)
  }
}

// 金额 2 位；计数整数 0 位，非整数 2 位
function precisionOf(comp: DashboardComponent): number {
  const suffix = comp.suffix || ''
  if (/[元¥￥]/.test(suffix)) return 2
  const value = aggregate(comp)
  if (value === null) return 0
  return Number.isInteger(value) ? 0 : 2
}

function gaugePercent(comp: DashboardComponent): number {
  const value = aggregate(comp)
  if (value === null) return 0
  const max = comp.bind?.max || 100
  return Math.max(0, Math.min(100, Math.round((value / max) * 100)))
}

function tableRows(comp: DashboardComponent): Array<{ company: string; industry: string; value: string }> {
  const bind = comp.bind
  if (!bind) return []
  return scopedCompanies.value.map((company) => {
    const table = tables.value[company.id]?.[bind.table]
    const value = fieldValue(table, bind.fieldKey)
    return {
      company: company.name,
      industry: industryLabel(company.industryKey) || '—',
      value: value === null ? '—' : `${value}${comp.suffix || ''}`,
    }
  })
}

async function load(): Promise<void> {
  loadError.value = ''
  try {
    const [layoutData, companyList] = await Promise.all([
      getDashboardLayout(props.cid),
      api.getCompanies(props.cid),
    ])
    layout.value = layoutData
    companies.value = companyList
    // 每公司拉 entity+finance，绑定字段可能跨表
    const entries = await Promise.all(
      companyList.map(async (company) => {
        const per: Record<string, CompanyTable> = {}
        for (const table of ['entity', 'finance'] as const) {
          try {
            per[table] = await api.getCompanyTable(props.cid, company.id, table)
          } catch {
          }
        }
        return [company.id, per] as const
      }),
    )
    tables.value = Object.fromEntries(entries)
    loaded.value = true
  } catch (e) {
    const message = errorMessage(e, '仪表盘加载失败')
    loadError.value = message
    ElMessage.error(message)
    loaded.value = true
  }
}

watch(
  () => props.cid,
  () => {
    if (props.cid) subscribeCompetition(props.cid)
    activeTab.value = '__all__'
    void load()
  },
  { immediate: true },
)

// 聚合相关资源变更后 400ms 去抖重拉，保留当前产业页签（dashboard=布局保存）
useResourceRefresh(
  ['contracts', 'companies', 'fiscal-years', 'basedata', 'regions', 'packages', 'dashboard'],
  load,
)
</script>

<style scoped>
.dashboard {
  min-width: 0;
}

.page-head {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 16px;
  row-gap: 10px;
  margin-bottom: 16px;
}

.page-head-main {
  flex: 1 1 auto;
  min-width: 0;
}

.page-head-main .page-title {
  margin-bottom: 6px;
}

.page-head > .el-button {
  flex-shrink: 0;
  margin-left: auto;
}

.dashboard-error {
  margin-bottom: 16px;
}

.industry-tabs {
  margin-bottom: 8px;
}

.scope-hint {
  margin-bottom: 16px;
  padding: 8px 12px;
  font-size: var(--font-sm);
  line-height: 1.7;
  color: var(--color-text-secondary);
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.scope-chip {
  display: inline-block;
  margin: 0 6px 0 0;
  padding: 1px 8px;
  font-size: var(--font-xs);
  color: var(--color-text-primary);
  background: var(--surface-sunken);
  border-radius: var(--radius-full);
}

.dash-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.dash-section:last-of-type {
  margin-bottom: 0;
}

/* 动画结束后交还 transform，保留悬停轻抬 */
.metric-grid > .metric-card,
.grid > * {
  animation-fill-mode: backwards;
}

.metric-card {
  min-width: 0;
}

.metric-card--gauge {
  display: flex;
  flex-direction: column;
}

.gauge-body {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
}

.metric-gauge {
  margin: 0;
}

.metric-card--gauge .metric-value {
  margin-top: 0;
}

/* 表盘默认蓝与全局品牌色不一致，需覆盖 */
.metric-gauge :deep(.el-progress-circle__path) {
  stroke: var(--color-primary);
}

.metric-note {
  margin-top: 6px;
  font-size: var(--font-xs);
  line-height: 1.6;
  color: var(--color-text-tertiary);
}

.metric-value :deep(.flash-updated) {
  display: inline-block;
  padding: 0 4px;
  margin: 0 -4px;
  border-radius: var(--radius-xs);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}

.comp {
  min-height: 120px;
}

.comp-wide {
  grid-column: span 2;
}

.comp-text {
  grid-column: span 2;
}

.comp-title {
  margin-bottom: 8px;
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
}

.text-body {
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.dash-skeleton {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.metric-skeleton {
  min-height: 118px;
}

.metric-skeleton-label {
  width: 46%;
}

.metric-skeleton-value {
  height: 28px;
  width: 62%;
}

.panel-skeleton {
  padding: 20px;
  min-height: 128px;
}

.panel-skeleton .panel-skeleton-title {
  width: 34%;
  height: 16px;
  margin-bottom: 16px;
}

@media (max-width: 640px) {
  .comp-wide,
  .comp-text {
    grid-column: auto;
  }
}
</style>
