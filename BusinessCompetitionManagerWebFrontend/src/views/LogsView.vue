<script setup lang="ts">
// 网络日志中心（仅系统超管）：网络日志查询/导出 + 登录设备管理
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh, Search } from '@element-plus/icons-vue'
import { exportNetworkLogs, getAdminDevices, getNetworkLogs } from '@/api'
import type { AdminDevice, NetworkLogItem, NetworkLogQuery } from '@/api/types'
import { formatDateTime, truncate } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const activeTab = ref<'network' | 'devices'>('network')

// ---------- 网络日志 ----------
const PAGE_SIZE = 20
const logs = ref<NetworkLogItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const selectedRows = ref<NetworkLogItem[]>([])
/** 展开行里摘要全文的展开状态（默认截断） */
const digestOpen = ref<Record<number, boolean>>({})

const filters = reactive({
  method: '',
  path: '',
  status: '',
  userId: '',
  traceId: '',
  range: null as [string, string] | null,
})

function buildQuery(): NetworkLogQuery {
  const query: NetworkLogQuery = {
    limit: PAGE_SIZE,
    offset: (page.value - 1) * PAGE_SIZE,
  }
  if (filters.method) query.method = filters.method
  if (filters.path.trim()) query.path = filters.path.trim()
  if (filters.status.trim()) query.status = Number(filters.status.trim())
  if (filters.userId.trim()) query.userId = Number(filters.userId.trim())
  if (filters.traceId.trim()) query.traceId = filters.traceId.trim()
  if (filters.range && filters.range.length === 2) {
    query.from = new Date(filters.range[0]).toISOString()
    query.to = new Date(filters.range[1]).toISOString()
  }
  return query
}

async function loadLogs(): Promise<void> {
  loading.value = true
  try {
    const res = await getNetworkLogs(buildQuery())
    logs.value = res.items ?? []
    total.value = res.total ?? 0
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  void loadLogs()
}

function resetFilters(): void {
  filters.method = ''
  filters.path = ''
  filters.status = ''
  filters.userId = ''
  filters.traceId = ''
  filters.range = null
  search()
}

function onSelectionChange(rows: NetworkLogItem[]): void {
  selectedRows.value = rows
}

function toggleDigest(id: number): void {
  digestOpen.value = { ...digestOpen.value, [id]: !digestOpen.value[id] }
}

/** 设备快照摘要：os / browser / screen 等键值拼接 */
function deviceSummary(snap: Record<string, string> | null | undefined): string {
  if (!snap || typeof snap !== 'object') return '—'
  const text = Object.entries(snap)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' · ')
  return text || '—'
}

// 状态码着色：2xx 成功 / 3xx 重定向 / 4xx 客户端错误 / 5xx 服务端错误
function statusTagType(status: number): 'success' | 'info' | 'warning' | 'danger' {
  if (status >= 500) return 'danger'
  if (status >= 400) return 'warning'
  if (status >= 300) return 'info'
  return 'success'
}

function methodTagType(method: string): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  if (method === 'GET') return 'primary'
  if (method === 'POST') return 'success'
  if (method === 'PATCH' || method === 'PUT') return 'warning'
  if (method === 'DELETE') return 'danger'
  return 'info'
}

// 导出选中记录（未勾选则导出当前全部）→ 客户端 JSON 下载
const exporting = ref(false)

async function exportLogs(): Promise<void> {
  exporting.value = true
  try {
    const ids = selectedRows.value.length > 0 ? selectedRows.value.map((r) => r.id) : undefined
    const result = await exportNetworkLogs(ids)
    const blob = new Blob([JSON.stringify(result.items ?? [], null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `network-logs-${Date.now()}.json`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    exporting.value = false
  }
}

// ---------- 设备管理 ----------
const devices = ref<AdminDevice[]>([])
const devicesLoading = ref(false)
const deviceUserId = ref('')
const devicesLoaded = ref(false)

async function loadDevices(): Promise<void> {
  devicesLoading.value = true
  try {
    devices.value = await getAdminDevices(
      deviceUserId.value.trim() ? Number(deviceUserId.value.trim()) : undefined,
    )
    devicesLoaded.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    devicesLoading.value = false
  }
}

// 切到设备管理时懒加载
function onTabChange(name: string | number): void {
  if (name === 'devices' && !devicesLoaded.value) void loadDevices()
}

onMounted(() => void loadLogs())
</script>

<template>
  <div class="logs-view">
    <h1 class="page-title">网络日志中心</h1>

    <el-card shadow="never" class="log-card">
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <!-- ===== 网络日志 ===== -->
        <el-tab-pane label="网络日志" name="network">
          <div class="filter-bar">
            <el-select v-model="filters.method" placeholder="方法" clearable style="width: 110px">
              <el-option label="GET" value="GET" />
              <el-option label="POST" value="POST" />
              <el-option label="PATCH" value="PATCH" />
              <el-option label="PUT" value="PUT" />
              <el-option label="DELETE" value="DELETE" />
            </el-select>
            <el-input
              v-model="filters.path"
              placeholder="路径关键字，如 /api/logs"
              clearable
              style="width: 200px"
            />
            <el-input
              v-model="filters.status"
              placeholder="状态码，如 200"
              clearable
              style="width: 130px"
            />
            <el-input v-model="filters.userId" placeholder="用户 ID" clearable style="width: 120px" />
            <el-input
              v-model="filters.traceId"
              placeholder="Trace ID"
              clearable
              style="width: 190px"
            />
            <el-date-picker
              v-model="filters.range"
              type="datetimerange"
              range-separator="至"
              start-placeholder="开始时间"
              end-placeholder="结束时间"
              value-format="YYYY-MM-DD HH:mm:ss"
              style="width: 340px"
            />
            <el-button type="primary" :icon="Search" @click="search">查询</el-button>
            <el-button @click="resetFilters">重置</el-button>
            <el-button
              type="success"
              :icon="Download"
              :loading="exporting"
              @click="exportLogs"
            >
              导出{{ selectedRows.length > 0 ? `选中（${selectedRows.length} 条）` : '当前全部' }}
            </el-button>
            <el-button :icon="Refresh" @click="loadLogs">刷新</el-button>
          </div>

          <el-table
            :data="logs"
            v-loading="loading"
            row-key="id"
            stripe
            size="small"
            @selection-change="onSelectionChange"
          >
            <el-table-column type="selection" width="42" />
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="expand-body">
                  <div class="expand-row">
                    <span class="expand-label">完整路径</span>
                    <span class="mono">{{ row.path }}{{ row.query ? `?${row.query}` : '' }}</span>
                  </div>
                  <div class="expand-row">
                    <span class="expand-label">设备快照</span>
                    <span class="mono">{{ deviceSummary(row.deviceSnapshot) }}</span>
                  </div>
                  <div class="expand-row">
                    <span class="expand-label">请求摘要</span>
                    <pre
                      class="digest"
                      :class="{ 'digest--open': digestOpen[row.id] }"
                    >{{ row.payloadDigest || '—' }}</pre>
                  </div>
                  <div class="expand-row">
                    <span class="expand-label">响应摘要</span>
                    <pre
                      class="digest"
                      :class="{ 'digest--open': digestOpen[row.id] }"
                    >{{ row.responseDigest || '—' }}</pre>
                  </div>
                  <el-button link type="primary" size="small" @click="toggleDigest(row.id)">
                    {{ digestOpen[row.id] ? '收起摘要' : '展开摘要全文' }}
                  </el-button>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="时间" width="160">
              <template #default="{ row }">{{ formatDateTime(row.occurredAt) }}</template>
            </el-table-column>
            <el-table-column label="方法" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="methodTagType(row.method)">{{ row.method }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="path" label="路径" min-width="220" show-overflow-tooltip />
            <el-table-column label="状态" width="86">
              <template #default="{ row }">
                <el-tag size="small" :type="statusTagType(row.status)">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="耗时(ms)" width="90">
              <template #default="{ row }">{{ row.durationMs ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="IP" min-width="125">
              <template #default="{ row }">{{ row.ip || '—' }}</template>
            </el-table-column>
            <el-table-column label="用户" width="120" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.username || (row.userId ? `用户 #${row.userId}` : '—') }}
              </template>
            </el-table-column>
            <el-table-column label="比赛" width="80">
              <template #default="{ row }">{{ row.competitionId ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="设备" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">{{ truncate(deviceSummary(row.deviceSnapshot), 32) }}</template>
            </el-table-column>
            <el-table-column label="Trace ID" width="210" show-overflow-tooltip>
              <template #default="{ row }">{{ row.traceId || '—' }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无日志数据" :image-size="72" />
            </template>
          </el-table>

          <div class="pager">
            <el-pagination
              v-model:current-page="page"
              :page-size="PAGE_SIZE"
              :total="total"
              layout="total, prev, pager, next"
              background
              @current-change="loadLogs"
            />
          </div>
        </el-tab-pane>

        <!-- ===== 设备管理 ===== -->
        <el-tab-pane label="设备管理" name="devices">
          <div class="filter-bar">
            <el-input
              v-model="deviceUserId"
              placeholder="用户 ID，留空查全部"
              clearable
              style="width: 180px"
              @keyup.enter="loadDevices"
            />
            <el-button type="primary" :icon="Search" @click="loadDevices">查询</el-button>
            <el-button :icon="Refresh" @click="loadDevices">刷新</el-button>
          </div>

          <el-table :data="devices" v-loading="devicesLoading" stripe size="small">
            <el-table-column label="用户" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.username || `用户 #${row.userId}` }}
              </template>
            </el-table-column>
            <el-table-column prop="os" label="操作系统" min-width="120" show-overflow-tooltip />
            <el-table-column prop="browser" label="浏览器" min-width="120" show-overflow-tooltip />
            <el-table-column prop="screen" label="屏幕" width="110" />
            <el-table-column label="IP" min-width="125">
              <template #default="{ row }">{{ row.ip || '—' }}</template>
            </el-table-column>
            <el-table-column label="首次登录" width="165">
              <template #default="{ row }">{{ formatDateTime(row.firstLoginAt) }}</template>
            </el-table-column>
            <el-table-column label="最近登录" width="165">
              <template #default="{ row }">{{ formatDateTime(row.lastLoginAt) }}</template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无设备记录" :image-size="72" />
            </template>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.logs-view {
  display: flex;
  flex-direction: column;
}

.log-note {
  margin-bottom: 16px;
}

.log-card {
  margin-bottom: 16px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

/* 展开行：请求/响应摘要等详情 */
.expand-body {
  padding: 8px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--color-surface-2);
}

.expand-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.expand-label {
  flex-shrink: 0;
  width: 64px;
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
  line-height: 22px;
}

.mono,
.digest {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: var(--font-xs);
  line-height: 1.7;
  color: var(--color-text-primary);
  word-break: break-all;
  white-space: pre-wrap;
}

/* 摘要默认截断（脱敏摘要很长时先省略展示） */
.digest {
  margin: 0;
  flex: 1;
  max-height: 44px;
  overflow: hidden;
}

.digest--open {
  max-height: 240px;
  overflow: auto;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
