<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createJob,
  getFiscalYearBackups,
  getFiscalYears,
  waitJob,
} from '@/api'
import type { FiscalYear, FiscalYearBackup } from '@/api/types'
import { useCountUp } from '@/composables/useMotion'
import { useResourceRefresh } from '@/composables/useNotifications'
import { formatDateTime, toDisplay } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

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

// ---------- 权限：系统超级管理员 / 本比赛超级管理员 ----------
const canManage = computed(() => auth.isSuperuser)

// ---------- 财年列表 ----------
const years = ref<FiscalYear[]>([])
const loading = ref(false)
const acting = ref(false)

async function loadYears(): Promise<void> {
  loading.value = true
  try {
    years.value = await getFiscalYears(props.cid)
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    loading.value = false
  }
}

// ---------- 关键数字（顶部指标卡，数值变化时滚动落位） ----------
const yearTotal = computed(() => years.value.length)
const openTotal = computed(() => years.value.filter((y) => y.status === 'OPEN').length)
const closedTotal = computed(() => years.value.filter((y) => y.status === 'CLOSED').length)
const backupTotal = computed(() =>
  years.value.reduce((sum, y) => sum + (y.backupCount ?? 0), 0),
)

const yearTotalShown = useCountUp(yearTotal)
const openTotalShown = useCountUp(openTotal)
const closedTotalShown = useCountUp(closedTotal)
const backupTotalShown = useCountUp(backupTotal)

// ---------- 开启 / 结束财年 ----------
/** 开启/结束财年都走后台任务：定时器重算、整表备份耗时较长，避免阻塞请求 */
async function runFiscalJob(kind: 'FISCAL_OPEN' | 'FISCAL_CLOSE', success: string): Promise<void> {
  acting.value = true
  try {
    const job = await createJob(props.cid, kind)
    const finalJob = await waitJob(props.cid, job.id)
    if (finalJob.status === 'FAILED') {
      ElMessage.error(finalJob.error || '执行失败')
      return
    }
    ElMessage.success(success)
    await loadYears()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    acting.value = false
  }
}

async function handleOpen(): Promise<void> {
  await runFiscalJob('FISCAL_OPEN', '财年已开启')
}

async function handleClose(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定结束当前财年？将自动备份各公司字段数据表（实体信息表 + 财务报表），并触发财年末定时器。',
      '结束财年',
      { type: 'warning', confirmButtonText: '结束财年', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  await runFiscalJob('FISCAL_CLOSE', '财年已结束，已自动备份')
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
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    backupsLoading.value = false
  }
}

/** 快照键值对（展开行展示） */
function snapshotEntries(row: FiscalYearBackup): Array<[string, string]> {
  return Object.entries(row.snapshot ?? {}).map(([k, v]) => [k, toDisplay(v)])
}

/** 年份切换：点「财年一览」的行即选中该财年，下方备份查看随之切换 */
function selectYear(row: FiscalYear): void {
  selectedFiscalYearId.value = row.id
  void loadBackups()
}

// 资源变更广播（400ms 去抖合并）：财年/合同/公司写操作后自动刷新财年列表
useResourceRefresh(['fiscal-years', 'contracts', 'companies'], loadYears)

// ---------- 初始化 ----------
onMounted(loadYears)
watch(() => props.cid, loadYears)
</script>

<template>
  <div class="fiscal-page page">
    <PageHeader title="财年管理">
      <template v-if="canManage" #actions>
        <el-button type="primary" :loading="acting" @click="handleOpen">开启财年</el-button>
        <el-button type="danger" :loading="acting" @click="handleClose">结束财年</el-button>
      </template>
    </PageHeader>

    <!-- 补录说明 -->
    <!-- 关键数字：财年 / 状态 / 备份总量 -->
    <div class="metric-grid anim-fade-in-up" :class="{ 'metrics-loading': loading && !years.length }">
      <div class="metric-card">
        <div class="metric-label">财年总数</div>
        <div class="metric-value">{{ yearTotalShown }}<span class="metric-unit">个</span></div>
      </div>
      <div class="metric-card">
        <div class="metric-label">开启中</div>
        <div class="metric-value">{{ openTotalShown }}<span class="metric-unit">个</span></div>
      </div>
      <div class="metric-card">
        <div class="metric-label">已结束</div>
        <div class="metric-value">{{ closedTotalShown }}<span class="metric-unit">个</span></div>
      </div>
      <div class="metric-card">
        <div class="metric-label">备份快照累计</div>
        <div class="metric-value">{{ backupTotalShown }}<span class="metric-unit">份</span></div>
      </div>
    </div>

    <!-- 财年列表 -->
    <section class="panel">
      <h2 class="section-title">
        财年一览
        <span class="section-hint">点击任一年度行，切换下方备份快照</span>
      </h2>
      <el-table
        v-loading="loading"
        :data="years"
        row-key="id"
        highlight-current-row
        border
        stripe
        class="year-table"
        style="width: 100%"
        @row-click="selectYear"
       size="small">
        <template #empty>
          <el-empty description="暂无财年"  :image-size="72" />
        </template>
        <el-table-column label="财年" width="120" align="center">
          <template #default="{ row }">
            <b class="fy-year value-num">{{ row.year }}</b>
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
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.openedAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结束时间" min-width="170">
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.closedAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="备份数" width="100" align="center">
          <template #default="{ row }">
            <span class="value-num">{{ row.backupCount }}</span>
          </template>
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
        <span class="backup-hint">展开行查看快照</span>
      </div>

      <el-table
        v-loading="backupsLoading"
        :data="backups"
        border
        stripe
        style="width: 100%"
       size="small">
        <template #empty>
          <el-empty
            :description="selectedFiscalYearId == null ? '请先选择财年' : '该财年暂无备份快照'"
           :image-size="72" />
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
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.createdAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="快照字段数" width="120" align="center">
          <template #default="{ row }">
            <span class="value-num">{{ Object.keys(row.snapshot ?? {}).length }}</span>
          </template>
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
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.backfill-alert {
  margin-bottom: 0;
}

.section-title {
  margin-bottom: 14px;
}

/* 标题旁的操作提示（告诉用户行可点击切换年份） */
.section-hint {
  margin-left: 0;
  font-size: var(--font-xs);
  font-weight: 400;
  color: var(--color-text-tertiary);
}

.panel {
  padding: 20px 22px;
}

/* 财年行可点击：整行都是年份切换的命中区 */
.year-table :deep(.el-table__row) {
  cursor: pointer;
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
