<script setup lang="ts">
// 字段日志检索：多条件过滤 + 分页 + 选中导出（JSON 下载）
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { exportFieldLogs, getFieldLogs } from '@/api'
import type { FieldLogItem, FieldLogQuery } from '@/api/types'
import { formatDateTime, toDisplay, truncate } from '@/utils/format'

const props = defineProps<{ cid: string }>()

const PAGE_SIZE = 20

const items = ref<FieldLogItem[]>([])
const total = ref(0)
const offset = ref(0)
const loading = ref(false)

// ---------- 过滤条件 ----------
const filters = reactive({
  fieldKey: '',
  contractId: '',
  operatorId: '',
  source: '',
  event: '',
  traceId: '',
})
const dateRange = ref<[Date, Date] | null>(null)

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
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    loading.value = false
  }
}

function search(): void {
  offset.value = 0
  void load()
}

function resetFilters(): void {
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
    ElMessage.success('导出成功')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
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

onMounted(() => void load())
</script>

<template>
  <div class="field-logs-page">
    <h1 class="page-title">字段日志</h1>

    <el-alert
      class="hint-alert"
      type="info"
      :closable="false"
      show-icon
      title="权限按公司可见性自动过滤（§15.2）：仅显示你有权查看的公司字段变更记录。"
    />

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">字段日志检索</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="load">刷新</el-button>
            <el-button type="primary" :icon="Download" @click="exportLogs">
              导出{{ selectedIds.length > 0 ? `选中（${selectedIds.length} 条）` : '当前全部' }}
            </el-button>
          </div>
        </div>
      </template>

      <!-- 过滤栏 -->
      <el-form :inline="true" class="filter-bar" @submit.prevent>
        <el-form-item label="字段键">
          <el-input
            v-model="filters.fieldKey"
            placeholder="如 cash"
            clearable
            style="width: 150px"
          />
        </el-form-item>
        <el-form-item label="合同 ID">
          <el-input
            v-model="filters.contractId"
            placeholder="数字"
            clearable
            style="width: 110px"
          />
        </el-form-item>
        <el-form-item label="操作人 ID">
          <el-input
            v-model="filters.operatorId"
            placeholder="数字"
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
      <el-table
        :data="items"
        v-loading="loading"
        stripe
        @selection-change="(rows: FieldLogItem[]) => (selectedRows = rows)"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="时间" width="165">
          <template #default="{ row }">{{ formatDateTime(row.occurredAt) }}</template>
        </el-table-column>
        <el-table-column prop="companyName" label="公司" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.companyName || '—' }}</template>
        </el-table-column>
        <el-table-column prop="fieldKey" label="字段键" min-width="130" show-overflow-tooltip />
        <el-table-column label="事件" width="100">
          <template #default="{ row }">
            <el-tag :type="eventTagType(row.event)" size="small">
              {{ EVENT_OPTIONS.find((o) => o.value === row.event)?.label ?? row.event }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="op" label="操作" width="80">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.op }}</el-tag>
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
        <el-table-column prop="roundNo" label="轮次" width="80" />
        <el-table-column label="Trace ID" width="130">
          <template #default="{ row }">
            <span :title="row.traceId">{{ truncate(row.traceId, 12) }}</span>
          </template>
        </el-table-column>
        <template #empty>暂无字段日志</template>
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
.filter-bar {
  margin-bottom: 4px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
