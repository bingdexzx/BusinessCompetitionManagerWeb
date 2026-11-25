<script setup lang="ts">
// 插件管理（仅系统超级管理员）：随比赛包上传的不可变插件注册表 + 执行审计
import { onMounted, ref } from 'vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Refresh, Search } from '@element-plus/icons-vue'
import { dryRunContractPlugin, getPlugins } from '@/api'
import type { PluginDryRunResult, PluginKind, PluginRecord } from '@/api/types'
import { formatDateTime, toDisplay, truncate } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { useResourceRefresh } from '@/composables/useNotifications'
// 插件类型标签
const KIND_LABELS: Record<PluginKind, string> = {
  CONTRACT: '合同插件',
  INDUSTRY: '产业插件',
}
const props = defineProps<{ cid: string }>()
const kindFilter = ref<'' | PluginKind>('')
const plugins = ref<PluginRecord[]>([])
const loading = ref(false)
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
async function load(): Promise<void> {
  loading.value = true
  try {
    plugins.value = await getPlugins(kindFilter.value || undefined, props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    loading.value = false;
  hasLoaded.value = true;
  }
}
function onFilterChange(): void {
  void load()
}
// 实时刷新：插件版本由比赛包导入注册（发 packages 事件），故两者都订阅
useResourceRefresh(['plugins', 'packages'], load)
// 复制完整 SHA-256（表格里只展示短哈希）
async function copySha(row: PluginRecord): Promise<void> {
  try {
    await navigator.clipboard.writeText(row.sha256)
    ElMessage.success('SHA-256 已复制')
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}
// 合同插件试跑：跑 check/apply 但不写库，用于启用前自查
const dryRunning = ref(false)
const dryRunVisible = ref(false)
const dryRunResult = ref<PluginDryRunResult | null>(null)
const dryRunTitle = ref('')
async function runDryRun(row: PluginRecord): Promise<void> {
  dryRunning.value = true
  dryRunTitle.value = `${row.name || row.key}（v${row.version}）`
  try {
    dryRunResult.value = await dryRunContractPlugin(props.cid, row.key, {
      // 指定版本，避免同 key 多版本时跑错
      inputs: undefined,
      companyIds: undefined,
    })
    dryRunVisible.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err, '试跑失败'))
  } finally {
    dryRunning.value = false
  }
}
// 审计详情 JSON 美化展示
function prettyDetail(detail: Record<string, unknown> | null | undefined): string {
  if (!detail) return '—'
  try {
    return JSON.stringify(detail, null, 2)
  } catch {
    return toDisplay(detail)
  }
}
onMounted(() => void load())
</script>
<template>
  <div class="plugins-view page">
    <PageHeader title="插件管理" />
    <el-card shadow="never" class="plugin-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <div class="card-heading">
            <span class="section-title">插件注册表</span>
            <span class="count-tip value-num">共 {{ plugins.length }} 个</span>
          </div>
          <div class="filter-bar">
            <el-select
              v-model="kindFilter"
              placeholder="插件类型"
              clearable
              style="width: 160px"
              @change="onFilterChange"
            >
              <el-option label="全部类型" value="" />
              <el-option label="合同插件（CONTRACT）" value="CONTRACT" />
              <el-option label="产业插件（INDUSTRY）" value="INDUSTRY" />
            </el-select>
            <el-button type="primary" :icon="Search" @click="load">查询</el-button>
            <el-button :icon="Refresh" @click="load">刷新</el-button>
          </div>
        </div>
      </template>
            <TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
<el-table :data="plugins" v-loading="loading && hasLoaded" row-key="id" stripe size="small" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="audit-body">
              <div class="audit-title">执行审计（{{ row.auditTrail?.length ?? 0 }}）</div>
              <el-empty
                v-if="!row.auditTrail?.length"
                description="暂无审计记录"
                :image-size="72"
              />
              <div v-for="(entry, i) in row.auditTrail" :key="i" class="audit-item">
                <div class="audit-head">
                  <el-tag size="small" type="info">{{ entry.event }}</el-tag>
                  <span class="audit-actor">{{ entry.actor }}</span>
                </div>
                <pre class="audit-detail">{{ prettyDetail(entry.detail) }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.kind === 'CONTRACT' ? 'primary' : 'success'">
              {{ KIND_LABELS[row.kind as PluginKind] ?? row.kind }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="key" label="标识（key）" min-width="150" show-overflow-tooltip />
        <el-table-column prop="name" label="名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="版本" width="90">
          <template #default="{ row }">
            <span class="value-num">{{ row.version }}</span>
          </template>
        </el-table-column>
        <el-table-column label="SHA-256" width="150">
          <template #default="{ row }">
            <span class="sha value-num">{{ truncate(row.sha256, 12) }}</span>
            <el-button
              link
              type="primary"
              size="small"
              class="op-muted"
              :icon="CopyDocument"
              title="复制完整 SHA-256"
              @click="copySha(row)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="fileName" label="文件名" min-width="160" show-overflow-tooltip />
        <el-table-column label="上传人" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.uploadedByUsername || (row.uploadedBy ? `用户 #${row.uploadedBy}` : '—') }}
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="165">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="{ row }">
            <el-button v-if="row.kind === 'CONTRACT'" link type="primary" size="small" :loading="dryRunning" @click="runDryRun(row)">
              试跑
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无插件" :image-size="72" />
        </template>
      </el-table>
    </el-card>
    <el-dialog v-model="dryRunVisible" :title="`插件试跑 · ${dryRunTitle}`" width="720px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="试跑只运行校验（check）与落账（apply）并回显结果，不会创建合同或写任何数据。"
        class="dryrun-hint"
      />
      <template v-if="dryRunResult">
        <el-alert
          v-if="dryRunResult.error"
          type="error"
          :closable="false"
          show-icon
          :title="dryRunResult.error"
        />
        <div class="dryrun-block">
          <b>参与方</b>
          <span v-for="(name, role) in dryRunResult.parties" :key="role" class="dryrun-item">
            {{ role }}：{{ name }}
          </span>
        </div>
        <div class="dryrun-block">
          <b>输入项</b>
          <span v-for="(value, key) in dryRunResult.inputs" :key="key" class="dryrun-item">
            {{ key }}={{ value }}
          </span>
        </div>
        <el-alert
          v-if="dryRunResult.problems.length"
          type="warning"
          :closable="false"
          show-icon
          :title="`校验（check）返回 ${dryRunResult.problems.length} 个问题：${dryRunResult.problems.join('；')}`"
          class="dryrun-hint"
        />
        <el-alert
          v-else-if="!dryRunResult.error"
          type="success"
          :closable="false"
          show-icon
          title="校验通过（无问题）"
          class="dryrun-hint"
        />
        <el-alert
          v-for="(warning, index) in dryRunResult.warnings"
          :key="index"
          type="warning"
          :closable="false"
          show-icon
          :title="warning"
          class="dryrun-hint"
        />
        <el-table :data="dryRunResult.effects" border size="small" class="dryrun-table" stripe>
          <el-table-column prop="company" label="公司/角色" min-width="120" />
          <el-table-column prop="field" label="字段" min-width="120" />
          <el-table-column prop="op" label="操作" width="80" align="center" />
          <el-table-column label="值" min-width="100">
            <template #default="{ row }">{{ toDisplay(row.value) }}</template>
          </el-table-column>
          <el-table-column label="区域" min-width="100">
            <template #default="{ row }">{{ row.region || '—' }}</template>
          </el-table-column>
          <template #empty>
            <el-empty description="落账（apply）没有产出效果" :image-size="72" />
          </template>
        </el-table>
      </template>
      <template #footer>
        <el-button @click="dryRunVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.dryrun-hint {
  margin-bottom: 10px;
}
.dryrun-block {
  margin-bottom: 10px;
}
.dryrun-item {
  margin-left: 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.dryrun-table {
  margin-top: 8px;
}
.plugins-view {
  display: flex;
  flex-direction: column;
}
.plugin-note {
  margin-bottom: 16px;
}
.plugin-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
/* 标题 + 数量：标题统一 section-title，数量弱化为辅助信息 */
.card-heading {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.card-heading .section-title {
  margin-bottom: 0;
}
.count-tip {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}
/* 复制哈希属于次级操作：默认弱化，悬停才上色 */
:deep(.op-muted.el-button.is-link) {
  color: var(--color-text-tertiary);
}
:deep(.op-muted.el-button.is-link:hover) {
  color: var(--color-primary);
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sha {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: var(--font-xs);
  margin-right: 4px;
}
/* 展开行：审计轨迹 */
.audit-body {
  padding: 8px 16px 12px;
  background: var(--color-surface-2);
}
.audit-title {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}
.audit-item {
  border: 1px solid var(--color-border);
  border-left: 3px solid rgba(var(--color-primary-rgb), 0.3);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  margin-bottom: 8px;
  background: var(--color-surface);
  transition: border-color var(--dur-fast) var(--ease-standard),
    box-shadow var(--dur-fast) var(--ease-standard);
}
.audit-item:hover {
  border-color: var(--color-border-strong);
  border-left-color: rgba(var(--color-primary-rgb), 0.6);
  box-shadow: var(--shadow-sm);
}
.audit-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.audit-actor {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.audit-detail {
  margin: 0;
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: var(--font-xs);
  line-height: 1.7;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 180px;
  overflow: auto;
}
</style>