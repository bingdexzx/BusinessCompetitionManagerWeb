<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  closeFiscalYear,
  getFiscalYearBackups,
  getFiscalYears,
  openFiscalYear,
} from '@/api'
import type { FiscalYear, FiscalYearBackup } from '@/api/types'
import { formatDateTime, toDisplay } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ cid: string }>()
const auth = useAuthStore()

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

// 财年状态展示映射
const STATUS_META: Record<string, { label: string; type: TagType }> = {
  OPEN: { label: '开启中', type: 'success' },
  CLOSED: { label: '已结束', type: 'info' },
  BACKFILL: { label: '补录', type: 'warning' },
}

function statusMeta(status: string): { label: string; type: TagType } {
  return STATUS_META[status] ?? { label: status, type: 'info' }
}

// ---------- 权限：系统超管 / 本比赛超管 ----------
const canManage = computed(
  () =>
    auth.isSuperuser ||
    auth.memberships.some((m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN'),
)

// ---------- 财年列表 ----------
const years = ref<FiscalYear[]>([])
const loading = ref(false)
const acting = ref(false)

async function loadYears(): Promise<void> {
  loading.value = true
  try {
    years.value = await getFiscalYears(props.cid)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    loading.value = false
  }
}

// ---------- 开启 / 结束财年 ----------
async function handleOpen(): Promise<void> {
  acting.value = true
  try {
    await openFiscalYear(props.cid)
    ElMessage.success('财年已开启')
    await loadYears()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    acting.value = false
  }
}

async function handleClose(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '结束财年将自动备份各公司字段数据表（实体信息表 + 财务报表），并触发财年末定时器。是否继续？',
      '结束财年',
      { type: 'warning', confirmButtonText: '结束财年', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  acting.value = true
  try {
    await closeFiscalYear(props.cid)
    ElMessage.success('财年已结束，已自动备份')
    await loadYears()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    acting.value = false
  }
}

// ---------- 备份查看 ----------
const selectedFiscalYearId = ref<number | null>(null)
const backups = ref<FiscalYearBackup[]>([])
const backupsLoading = ref(false)

async function loadBackups(): Promise<void> {
  if (selectedFiscalYearId.value == null) {
    backups.value = []
    return
  }
  backupsLoading.value = true
  try {
    backups.value = await getFiscalYearBackups(props.cid, selectedFiscalYearId.value)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '操作失败')
  } finally {
    backupsLoading.value = false
  }
}

/** 快照键值对（展开行展示） */
function snapshotEntries(row: FiscalYearBackup): Array<[string, string]> {
  return Object.entries(row.snapshot ?? {}).map(([k, v]) => [k, toDisplay(v)])
}

// ---------- 初始化 ----------
onMounted(loadYears)
watch(() => props.cid, loadYears)
</script>

<template>
  <div class="fiscal-page">
    <div class="page-toolbar">
      <h1 class="page-title">财年管理</h1>
      <div v-if="canManage" class="page-actions">
        <el-button type="primary" :loading="acting" @click="handleOpen">开启财年</el-button>
        <el-button type="danger" :loading="acting" @click="handleClose">结束财年</el-button>
      </div>
    </div>

    <!-- 补录说明 -->
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="补录说明"
      description="补录合同在合同工作台创建（勾选补录 + 选择财年），需超管审核，以财年末快照为执行基准。"
      class="backfill-alert"
    />

    <!-- 财年列表 -->
    <section class="panel">
      <h2 class="section-title">财年一览</h2>
      <el-table v-loading="loading" :data="years" border stripe style="width: 100%">
        <template #empty>
          <el-empty description="暂无财年" />
        </template>
        <el-table-column label="财年" width="120" align="center">
          <template #default="{ row }">
            <b class="fy-year">{{ row.year }}</b>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta(row.status).type">
              {{ row.statusLabel || statusMeta(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="开启时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.openedAt) }}</template>
        </el-table-column>
        <el-table-column label="结束时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.closedAt) }}</template>
        </el-table-column>
        <el-table-column label="备份数" width="100" align="center">
          <template #default="{ row }">{{ row.backupCount }}</template>
        </el-table-column>
      </el-table>
    </section>

    <!-- 备份查看 -->
    <section class="panel">
      <h2 class="section-title">备份查看</h2>
      <div class="backup-toolbar">
        <el-select
          v-model="selectedFiscalYearId"
          clearable
          placeholder="选择财年查看备份快照"
          style="width: 220px"
          @change="loadBackups"
        >
          <el-option
            v-for="fy in years"
            :key="fy.id"
            :label="`${fy.year} 财年（备份 ${fy.backupCount}）`"
            :value="fy.id"
          />
        </el-select>
        <span class="backup-hint">结束财年时自动备份各公司字段数据表，展开行查看快照键值</span>
      </div>

      <el-table
        v-loading="backupsLoading"
        :data="backups"
        border
        stripe
        style="width: 100%"
      >
        <template #empty>
          <el-empty
            :description="selectedFiscalYearId == null ? '请先选择财年' : '该财年暂无备份快照'"
          />
        </template>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="snapshot-box">
              <div v-for="([k, v]) in snapshotEntries(row)" :key="k" class="snapshot-row">
                <span class="snapshot-key">{{ k }}</span>
                <span class="snapshot-value">{{ v }}</span>
              </div>
              <div v-if="snapshotEntries(row).length === 0" class="snapshot-empty">
                快照为空（{}）
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="companyName" label="公司" min-width="180" />
        <el-table-column label="备份时间" min-width="170">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="快照字段数" width="120" align="center">
          <template #default="{ row }">{{ Object.keys(row.snapshot ?? {}).length }}</template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped lang="scss">
.fiscal-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.page-toolbar .page-title {
  margin-bottom: 0;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.backfill-alert {
  margin-bottom: 0;
}

.section-title {
  font-size: var(--font-lg);
  font-weight: 700;
  color: var(--color-text-primary);
  margin-bottom: 14px;
}

.panel {
  padding: 20px 22px;
}

.fy-year {
  font-size: var(--font-lg);
  color: var(--color-text-primary);
}

.backup-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.backup-hint {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}

.snapshot-box {
  padding: 8px 16px;
  background: var(--surface-sunken);
}
.snapshot-row {
  display: flex;
  gap: 12px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--color-border);
  font-size: var(--font-sm);
}
.snapshot-row:last-child {
  border-bottom: none;
}
.snapshot-key {
  flex: 0 0 180px;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.snapshot-value {
  flex: 1;
  color: var(--el-text-color-regular);
  word-break: break-all;
}
.snapshot-empty {
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}
</style>
