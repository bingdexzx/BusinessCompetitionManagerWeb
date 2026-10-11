<script setup lang="ts">
// 审计流水：比赛内审计日志（超管），简单过滤 + payload JSON 展开
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { getAuditLogs } from '@/api'
import type { AuditLogItem } from '@/api/types'
import { formatDateTime, truncate } from '@/utils/format'

const props = defineProps<{ cid: string }>()

const items = ref<AuditLogItem[]>([])
const loading = ref(false)

// 简单过滤：动作关键字 + 操作人 ID（对已拉取列表做本地过滤）
const actionKeyword = ref('')
const actorIdInput = ref('')

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = await getAuditLogs(props.cid, { limit: 100 })
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  actionKeyword.value = ''
  actorIdInput.value = ''
}

const filteredItems = computed<AuditLogItem[]>(() => {
  const keyword = actionKeyword.value.trim().toLowerCase()
  const actorId = actorIdInput.value.trim()
  return items.value.filter((row) => {
    if (keyword && !row.action.toLowerCase().includes(keyword)) return false
    if (actorId && String(row.actorId ?? '') !== actorId) return false
    return true
  })
})

/** payload 格式化为 JSON 文本 */
function prettyJson(payload: Record<string, unknown> | null | undefined): string {
  try {
    return JSON.stringify(payload ?? {}, null, 2)
  } catch {
    return String(payload)
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="audit-log-page">
    <h1 class="page-title">审计流水</h1>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">审计流水（共 {{ filteredItems.length }} 条）</span>
          <div class="card-actions">
            <el-input
              v-model="actionKeyword"
              placeholder="动作关键字"
              clearable
              style="width: 160px"
            />
            <el-input v-model="actorIdInput" placeholder="操作人 ID" clearable style="width: 120px" />
            <el-button @click="resetFilters">重置</el-button>
            <el-button :icon="Refresh" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <el-table :data="filteredItems" v-loading="loading" stripe>
        <el-table-column label="时间" width="165">
          <template #default="{ row }">{{ formatDateTime(row.occurredAt) }}</template>
        </el-table-column>
        <el-table-column prop="action" label="动作" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作人" width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.actorUsername || row.actorId || '—' }}</template>
        </el-table-column>
        <el-table-column prop="target" label="对象" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.target || '—' }}</template>
        </el-table-column>
        <el-table-column label="payload" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ Object.keys(row.payload ?? {}).length }} 项</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Trace ID" width="140">
          <template #default="{ row }">
            <span :title="row.traceId">{{ truncate(row.traceId, 14) }}</span>
          </template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="payload-wrap">
              <div class="payload-label">payload（JSON）</div>
              <pre class="json-pre">{{ prettyJson(row.payload) }}</pre>
            </div>
          </template>
        </el-table-column>
        <template #empty>暂无审计记录</template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.audit-log-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
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
.payload-wrap {
  padding: 8px 16px 12px;
}
.payload-label {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
  margin-bottom: 6px;
}
.json-pre {
  margin: 0;
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
</style>
