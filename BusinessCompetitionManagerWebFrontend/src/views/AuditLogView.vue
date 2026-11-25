<script setup lang="ts">
// 比赛内审计流水：动作中文化 + 对象可读/可跳转 + 关键信息摘要 + 按日期分组 + 原始数据展开
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { RouterLink } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getAuditLogs } from '@/api'
import type { AuditLogItem } from '@/api/types'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useCatalog } from '@/composables/useCatalog'
import { formatDateTime, toDisplay } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()

const { contractTypeLabel } = useCatalog(() => props.cid)

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

interface ActionMeta {
  label: string
  group: string
  type: TagType
}

// 动作代号 → 中文名 / 分类 / 语义色（新增动作只需在这里登记一行）
const ACTION_META: Record<string, ActionMeta> = {
  CONTRACT_CREATE: { label: '创建合同', group: '合同', type: 'primary' },
  CONTRACT_SUBMIT: { label: '提交合同', group: '合同', type: 'primary' },
  CONTRACT_CONFIRM: { label: '参与方确认', group: '合同', type: 'success' },
  CONTRACT_RETRY_EXECUTE: { label: '重试执行', group: '合同', type: 'warning' },
  CONTRACT_MOD_APPLY: { label: '申请修改', group: '合同', type: 'warning' },
  CONTRACT_MOD_REVIEW: { label: '修改审核', group: '合同', type: 'warning' },
  CONTRACT_MOD_OTHER_PARTY: { label: '其他方表态', group: '合同', type: 'warning' },
  CONTRACT_MOD_SUBMIT: { label: '提交修改', group: '合同', type: 'warning' },
  CONTRACT_BACKFILL_REVIEW: { label: '补录审核', group: '合同', type: 'warning' },
  CONTRACT_DELETE: { label: '删除合同', group: '合同', type: 'danger' },
  STOCK_ORDER_CREATE: { label: '股票下单', group: '股票', type: 'primary' },
  STOCK_ORDER_CANCEL: { label: '股票撤单', group: '股票', type: 'info' },
  STOCK_ADVANCE_ROUND: { label: '推进交易轮次', group: '股票', type: 'info' },
}
const ACTION_GROUPS = ['合同', '股票', '其他']

function actionMeta(action: string): ActionMeta {
  return ACTION_META[action] ?? { label: action, group: '其他', type: 'info' }
}

// payload 字段 → 中文名（未知字段原样展示）
const FIELD_LABELS: Record<string, string> = {
  contractTypeKey: '合同类型',
  type: '合同类型',
  unifiedNumber: '统一编号',
  rolledBackRound: '回滚轮次',
  roundNo: '轮次',
  reason: '理由',
  note: '意见',
  approve: '审核结果',
  partyRole: '参与方',
  code: '股票代码',
  side: '方向',
  price: '价格',
  quantity: '数量',
  advanced: '推进',
  skipped: '跳过',
  marketMakerOrders: '做市商挂单',
}

const items = ref<AuditLogItem[]>([])
const loading = ref(false)
const LIMIT = 200

const filters = reactive({
  action: '' as string,
  actor: '',
  range: null as [Date, Date] | null,
})

function buildQuery(): Parameters<typeof getAuditLogs>[1] {
  const query: Parameters<typeof getAuditLogs>[1] = { limit: LIMIT }
  if (filters.action) query.action = filters.action
  if (filters.actor.trim()) query.actor = filters.actor.trim()
  if (filters.range) {
    query.from = filters.range[0].toISOString()
    query.to = filters.range[1].toISOString()
  }
  return query
}

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = await getAuditLogs(props.cid, buildQuery())
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    loading.value = false
  }
}

function search(): void {
  void load()
}

function resetFilters(): void {
  filters.action = ''
  filters.actor = ''
  filters.range = null
  void load()
}

/** 动作下拉：已知动作按分组排列，未知动作（历史/新动作）归入「其他」 */
const actionOptions = computed(() => {
  const known = Object.entries(ACTION_META).map(([code, meta]) => ({ code, ...meta }))
  const extras = Array.from(new Set(items.value.map((r) => r.action)))
    .filter((code) => !(code in ACTION_META))
    .map((code) => ({ code, label: code, group: '其他', type: 'info' as TagType }))
  return [...known, ...extras]
})

function actionsInGroup(group: string): Array<{ code: string; label: string }> {
  return actionOptions.value.filter((o) => o.group === group)
}

/** 按日期分组（今天 / 昨天 / 具体日期），扫描流水更顺 */
function dateLabel(iso: string): string {
  const date = new Date(iso)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (date.toDateString() === today.toDateString()) return '今天'
  if (date.toDateString() === yesterday.toDateString()) return '昨天'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const groups = computed<Array<{ label: string; rows: AuditLogItem[] }>>(() => {
  const out: Array<{ label: string; rows: AuditLogItem[] }> = []
  for (const row of items.value) {
    const label = dateLabel(row.occurredAt)
    const last = out[out.length - 1]
    if (last && last.label === label) last.rows.push(row)
    else out.push({ label, rows: [row] })
  }
  return out
})

function timeOnly(iso: string): string {
  return formatDateTime(iso).slice(11)
}

/** 对象：合同/委托显示为可读名称；合同对象可跳转详情 */
function targetLabel(row: AuditLogItem): string {
  if (row.action.startsWith('CONTRACT_') && row.target) return `合同 #${row.target}`
  if (row.action.startsWith('STOCK_ORDER_') && row.target) return `委托 #${row.target}`
  if (row.action === 'STOCK_ADVANCE_ROUND') return '股票市场'
  return row.target || '—'
}

function targetLink(row: AuditLogItem): string | null {
  if (row.action.startsWith('CONTRACT_') && /^\d+$/.test(row.target)) {
    return `/competitions/${props.cid}/contracts/${row.target}`
  }
  return null
}

/** 设备摘要：浏览器 · 系统 · IP（Unknown 不展示） */
function deviceText(row: AuditLogItem): string {
  const device = (row.payload?.device ?? {}) as Record<string, string>
  const parts = [device.browser, device.os, device.ip]
    .filter((v) => v && v !== 'Unknown')
  return parts.join(' · ')
}

interface Summary {
  key: string
  label: string
  value: string
}

/** payload 摘要（去掉冗长的 device 快照） */
function summary(row: AuditLogItem): Summary[] {
  const out: Summary[] = []
  for (const [key, value] of Object.entries(row.payload ?? {})) {
    if (key === 'device') continue
    let text = toDisplay(value)
    if (key === 'contractTypeKey' || (key === 'type' && typeof value === 'string')) {
      text = contractTypeLabel(String(value)) || text
    }
    if (key === 'approve') text = value ? '通过' : '驳回'
    out.push({ key, label: FIELD_LABELS[key] ?? key, value: text })
  }
  return out
}

/** 原始数据（折叠）；同一时刻只展开一条 */
const expandedId = ref<number | null>(null)

function toggleDetail(id: number): void {
  expandedId.value = expandedId.value === id ? null : id
}

function prettyJson(payload: Record<string, unknown> | null | undefined): string {
  try {
    return JSON.stringify(payload ?? {}, null, 2)
  } catch {
    return String(payload)
  }
}

// 资源变更广播（400ms 去抖合并）：审计条目由合同/股票写操作产生，故一并订阅
useResourceRefresh(['audit-logs', 'logs', 'contracts', 'stock'], load)

onMounted(() => void load())
</script>

<template>
  <div class="audit-log-page page">
    <PageHeader title="审计流水" />

    <section class="panel audit-panel anim-fade-in-up">
      <div class="panel-head">
        <div class="panel-heading">
          <h2 class="section-title">审计流水</h2>
          <span class="count-tip value-num">共 {{ items.length }} 条</span>
        </div>
        <div class="card-actions">
          <el-button :icon="Refresh" @click="load">刷新</el-button>
        </div>
      </div>

      <div class="toolbar query-toolbar">
        <el-select
            v-model="filters.action"
            placeholder="全部动作"
            clearable
            filterable
            style="width: 170px"
          >
            <el-option-group
              v-for="group in ACTION_GROUPS"
              :key="group"
              :label="group"
            >
              <el-option
                v-for="opt in actionsInGroup(group)"
                :key="opt.code"
                :label="opt.label"
                :value="opt.code"
              />
            </el-option-group>
          </el-select>
          <el-input
            v-model="filters.actor"
            placeholder="操作人（用户名/ID）"
            clearable
            style="width: 180px"
            @keyup.enter="search"
          />
          <el-date-picker
            v-model="filters.range"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            style="width: 320px"
          />
          <el-button type="primary" :icon="Search" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </div>

      <!-- 首屏骨架；实时重拉时保留列表，避免闪白 -->
      <div v-if="loading && !items.length" class="audit-skeleton">
        <div v-for="i in 4" :key="i" class="skeleton skeleton-line" />
      </div>
      <el-empty v-else-if="!items.length" description="暂无审计记录" :image-size="72" />

      <div v-else class="audit-groups">
        <section v-for="group in groups" :key="group.label" class="audit-group">
          <h3 class="audit-group-title">{{ group.label }}</h3>
          <ol class="audit-list">
            <li v-for="row in group.rows" :key="row.id" class="audit-row">
              <span class="audit-time value-num">{{ timeOnly(row.occurredAt) }}</span>

              <el-tag
                :type="actionMeta(row.action).type"
                size="small"
                effect="plain"
                class="audit-action-tag"
              >
                {{ actionMeta(row.action).label }}
              </el-tag>

              <div class="audit-content">
                <div class="audit-line">
                  <span class="audit-object">
                    <RouterLink
                      v-if="targetLink(row)"
                      :to="targetLink(row)!"
                      class="object-link"
                    >{{ targetLabel(row) }}</RouterLink>
                    <template v-else>{{ targetLabel(row) }}</template>
                  </span>
                  <span class="audit-dot" aria-hidden="true">·</span>
                  <span class="audit-actor">
                    {{ row.actorUsername || (row.actorId ? `用户 #${row.actorId}` : '—') }}
                  </span>
                  <template v-if="deviceText(row)">
                    <span class="audit-dot" aria-hidden="true">·</span>
                    <span class="audit-device">{{ deviceText(row) }}</span>
                  </template>
                </div>

                <div v-if="summary(row).length" class="audit-chips">
                  <span v-for="item in summary(row)" :key="item.key" class="audit-chip">
                    <em>{{ item.label }}</em>
                    <b>{{ item.value }}</b>
                  </span>
                </div>

                <button
                  type="button"
                  class="detail-toggle pressable"
                  @click="toggleDetail(row.id)"
                >
                  {{ expandedId === row.id ? '收起原始数据' : '原始数据' }}
                </button>
                <pre v-if="expandedId === row.id" class="json-pre">{{ prettyJson(row.payload) }}</pre>
              </div>
            </li>
          </ol>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.audit-log-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.audit-panel {
  padding: 18px 20px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin: 0 -20px 14px;
  padding: 0 20px 12px;
  border-bottom: 1px solid var(--color-border);
}

.panel-heading {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.panel-heading .section-title {
  margin-bottom: 0;
}

.count-tip {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}

.card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.query-toolbar {
  padding: 12px 14px;
  margin-bottom: 14px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.audit-skeleton {
  padding: 8px 0;
}

/* ===== 日期分组 ===== */
.audit-group + .audit-group {
  margin-top: 6px;
}

.audit-group-title {
  margin: 14px 0 6px;
  font-size: var(--font-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--color-text-tertiary);
}

.audit-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.audit-row {
  display: grid;
  grid-template-columns: 62px auto minmax(0, 1fr);
  column-gap: 10px;
  align-items: start;
  padding: 9px 0;
  border-bottom: 1px dashed var(--color-border);
}

.audit-row:last-child {
  border-bottom: 0;
}

.audit-time {
  padding-top: 1px;
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}

.audit-action-tag {
  margin-top: 1px;
}

.audit-content {
  min-width: 0;
}

.audit-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  font-size: var(--font-sm);
}

.audit-object {
  font-weight: 600;
  color: var(--color-text-primary);
}

.object-link {
  color: var(--color-primary);
  text-decoration: none;
}

.object-link:hover {
  text-decoration: underline;
}

.audit-dot {
  color: var(--color-text-tertiary);
}

.audit-actor {
  color: var(--color-text-secondary);
}

.audit-device {
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}

/* 关键信息摘要（payload 扁平化为标签，替代裸 JSON） */
.audit-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
}

.audit-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  padding: 1px 8px;
  border-radius: var(--radius-xs);
  background: var(--surface-sunken);
  font-size: var(--font-xs);
  line-height: 1.8;
}

.audit-chip em {
  font-style: normal;
  color: var(--color-text-tertiary);
}

.audit-chip b {
  font-weight: 600;
  color: var(--color-text-primary);
  word-break: break-all;
}

.detail-toggle {
  margin-top: 4px;
  padding: 0;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: var(--font-xs);
  cursor: pointer;
}

.detail-toggle:hover {
  text-decoration: underline;
}

.json-pre {
  margin: 8px 0 0;
  padding: 10px 12px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  font-size: var(--font-xs);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 320px;
  overflow: auto;
}

/* 窄屏：时间与动作换行到内容上方 */
@media (max-width: 760px) {
  .audit-row {
    grid-template-columns: 56px minmax(0, 1fr);
    row-gap: 4px;
  }
  .audit-action-tag {
    grid-column: 2;
  }
  .audit-content {
    grid-column: 1 / -1;
  }
}
</style>
