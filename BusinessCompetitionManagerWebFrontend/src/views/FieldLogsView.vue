<script setup lang="ts">
// 字段日志检索：多条件过滤 + 分页 + 选中导出（JSON 下载）
import { computed, onMounted, reactive, ref } from 'vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import {
  exportFieldLogs,
  exportFieldLogsXlsx,
  getFieldLogCompanyOptions,
  getFieldLogs,
  saveBlob,
} from '@/api'
import type { FieldLogCompanyOption, FieldLogItem, FieldLogQuery } from '@/api/types'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useCatalog } from '@/composables/useCatalog'
import { formatDateTime, toDisplay, truncate } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { opLabel } from '@/utils/fieldOps'
const props = defineProps<{ cid: string }>()
// 字段键 → 中文名（筛选与列表都不显示 cash 这类键）
const { fieldLabel, fieldOptions } = useCatalog(() => props.cid)
const PAGE_SIZE = 20
const items = ref<FieldLogItem[]>([])
const total = ref(0)
const offset = ref(0)
const loading = ref(false)
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
// ---------- 过滤条件 ----------
const filters = reactive({
  companyId: '' as number | '' | undefined,
  fieldKey: '',
  contractId: '',
  operatorId: '',
  source: '',
  event: '',
  traceId: '',
})
const dateRange = ref<[Date, Date] | null>(null)
// 公司下拉：来自「字段日志公司选项」接口——只含本比赛（且有字段日志）的公司，
// 避免比赛包导入产生的外部公司出现在筛选里（比赛级隔离）。
const companies = ref<FieldLogCompanyOption[]>([])
const companiesLoading = ref(false)
async function loadCompanies(): Promise<void> {
  companiesLoading.value = true
  try {
    companies.value = await getFieldLogCompanyOptions(props.cid)
  } catch {
    companies.value = [] // 公司列表为筛选辅助数据，失败不打断日志检索
  } finally {
    companiesLoading.value = false
  }
}
const SOURCE_OPTIONS = [
  { value: 'CONTRACT_POST', label: '合同落账' },
  { value: 'CONTRACT_ROLLBACK', label: '合同回滚' },
  { value: 'CONTRACT_REPOST', label: '合同重落账' },
  { value: 'BACKFILL_SYNC', label: '补录同步' },
  { value: 'FY_TIMER', label: '财年定时器' },
  { value: 'CALC', label: '公式计算' },
  { value: 'MANUAL', label: '手工修改' },
  { value: 'SCHEMA_MIGRATE', label: '字段迁移' },
]
const EVENT_OPTIONS = [
  { value: 'VALUE_CHANGE', label: '值变更' },
  { value: 'SCHEMA_CHANGE', label: '结构变更' },
]
function buildQuery(): FieldLogQuery {
  const query: FieldLogQuery = { limit: PAGE_SIZE, offset: offset.value }
  if (typeof filters.companyId === 'number') query.companyId = filters.companyId
  if (filters.fieldKey.trim()) query.fieldKey = filters.fieldKey.trim()
  if (filters.contractId.trim()) query.contractId = Number(filters.contractId.trim())
  if (filters.operatorId.trim()) query.operatorId = Number(filters.operatorId.trim())
  if (filters.source) query.source = filters.source
  if (filters.event) query.event = filters.event
  if (filters.traceId.trim()) query.traceId = filters.traceId.trim()
  if (dateRange.value) {
    query.from = dateRange.value[0].toISOString()
    query.to = dateRange.value[1].toISOString()
  }
  return query
}
async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await getFieldLogs(props.cid, buildQuery())
    items.value = page.items
    total.value = page.total
    selectedRows.value = []
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    loading.value = false;
  hasLoaded.value = true;
  }
}
function search(): void {
  offset.value = 0
  void load()
}
function resetFilters(): void {
  filters.companyId = ''
  filters.fieldKey = ''
  filters.contractId = ''
  filters.operatorId = ''
  filters.source = ''
  filters.event = ''
  filters.traceId = ''
  dateRange.value = null
  search()
}
const page = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
function onPageChange(next: number): void {
  offset.value = (next - 1) * PAGE_SIZE
  void load()
}
// ---------- 导出 ----------
const selectedRows = ref<FieldLogItem[]>([])
const selectedIds = computed(() => selectedRows.value.map((r) => r.id))
const exportingXlsx = ref(false)
async function exportExcel(): Promise<void> {
  exportingXlsx.value = true
  try {
    const blob = await exportFieldLogsXlsx(props.cid, selectedIds.value)
    saveBlob(blob, '字段日志.xlsx')
    ElMessage.success('字段日志已导出')
  } catch (e) {
    ElMessage.error(errorMessage(e, '导出失败'))
  } finally {
    exportingXlsx.value = false
  }
}
async function exportLogs(): Promise<void> {
  try {
    const ids = selectedIds.value.length > 0 ? selectedIds.value : undefined
    const result = await exportFieldLogs(props.cid, ids)
    // 客户端生成 JSON 文件下载
    const blob = new Blob([JSON.stringify(result.items ?? [], null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `field-logs-${Date.now()}.json`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('日志已导出')
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}
/** 事件标签配色 */
function eventTagType(event: string): 'primary' | 'warning' | 'info' {
  if (event === 'SCHEMA_CHANGE') return 'warning'
  if (event === 'VALUE_CHANGE') return 'primary'
  return 'info'
}
/** before → after 展示 */
function changeText(row: FieldLogItem): string {
  return `${toDisplay(row.before)} → ${toDisplay(row.after)}`
}
// 资源变更广播（400ms 去抖合并）：日志/合同/公司/基础数据写操作后重拉当前页（分页与过滤条件保留）
useResourceRefresh(['logs', 'contracts', 'companies', 'basedata'], load)
onMounted(() => {
  void loadCompanies()
  void load()
})
</script>
<template>
  <div class="field-logs-page page">
    <PageHeader title="字段日志" />
    <el-card shadow="never" class="section-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <span class="card-title">字段日志检索</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="load">刷新</el-button>
            <el-button type="primary" :icon="Download" @click="exportLogs">
              导出{{ selectedIds.length > 0 ? `选中（${selectedIds.length} 条）` : '当前全部' }}
            </el-button>
            <el-button :loading="exportingXlsx" @click="exportExcel">导出 Excel</el-button>
          </div>
        </div>
      </template>
      <!-- 过滤栏（单条工具条：所有筛选项 + 查询/重置在一行内换行排列） -->
      <el-form :inline="true" class="filter-bar query-toolbar" @submit.prevent>
        <el-form-item label="公司">
          <el-select
            v-model="filters.companyId"
            filterable
            clearable
            :loading="companiesLoading"
            placeholder="全部公司（本比赛）"
            style="width: 200px"
          >
            <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="字段">
          <el-select
            v-model="filters.fieldKey"
            filterable
            clearable
            placeholder="全部字段"
            style="width: 180px"
          >
            <el-option
              v-for="opt in fieldOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="合同 ID">
          <el-input
            v-model="filters.contractId"
            placeholder="请输入数字"
            clearable
            style="width: 110px"
          />
        </el-form-item>
        <el-form-item label="操作人 ID">
          <el-input
            v-model="filters.operatorId"
            placeholder="请输入数字"
            clearable
            style="width: 110px"
          />
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="filters.source" placeholder="全部" clearable style="width: 150px">
            <el-option
              v-for="opt in SOURCE_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="事件">
          <el-select v-model="filters.event" placeholder="全部" clearable style="width: 130px">
            <el-option
              v-for="opt in EVENT_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="dateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
          />
        </el-form-item>
        <el-form-item label="Trace ID">
          <el-input v-model="filters.traceId" clearable style="width: 190px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
      <!-- 结果表 -->
            <TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
<el-table
        :data="items"
        v-loading="loading && hasLoaded"
        stripe
        @selection-change="(rows: FieldLogItem[]) => (selectedRows = rows)"
       size="small" border class="table--sticky-head" max-height="calc(100vh - 330px)">
        <el-table-column type="selection" width="44" />
        <el-table-column label="时间" width="165">
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.occurredAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="companyName" label="公司" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.companyName || (row.regionName ? `区域·${row.regionName}` : '—') }}
          </template>
        </el-table-column>
        <el-table-column label="字段" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ fieldLabel(row.fieldKey) }}</template>
        </el-table-column>
        <el-table-column label="事件" width="100">
          <template #default="{ row }">
            <el-tag :type="eventTagType(row.event)" size="small">
              {{ EVENT_OPTIONS.find((o) => o.value === row.event)?.label ?? row.event }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="op" label="操作" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ opLabel(row.op) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="变更（前 → 后）" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span :title="changeText(row)">{{ truncate(changeText(row), 40) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">{{ row.sourceLabel || row.source }}</template>
        </el-table-column>
        <el-table-column prop="operatorUsername" label="操作人" width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.operatorUsername || '—' }}</template>
        </el-table-column>
        <el-table-column prop="roundNo" label="轮次" width="80">
          <template #default="{ row }">
            <span class="value-num">{{ row.roundNo }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Trace ID" width="130">
          <template #default="{ row }">
            <span class="mono value-num" :title="row.traceId">{{ truncate(row.traceId, 12) }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无字段日志" :image-size="72" />
        </template>
      </el-table>
      <!-- 分页 -->
      <div class="pager">
        <el-pagination
          :current-page="page"
          :page-size="PAGE_SIZE"
          :total="total"
          layout="total, prev, pager, next"
          background
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>
<style scoped>
.field-logs-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.hint-alert {
  margin-bottom: 0;
}
.section-card {
  margin: 0;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.card-title {
  font-weight: 600;
}
.card-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
/* 一条工具条：所有筛选项集中在一块浅底面板里，标签弱化、控件紧凑 */
.query-toolbar {
  padding: 12px 14px 2px;
  margin-bottom: 14px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
.query-toolbar :deep(.el-form-item) {
  margin-bottom: 10px;
  margin-right: 12px;
}
.query-toolbar :deep(.el-form-item__label) {
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
}
.mono {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>