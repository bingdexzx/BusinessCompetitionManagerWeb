<script setup lang="ts">
// 审计流水：比赛内审计日志（超管），简单过滤 + payload JSON 展开
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { getAuditLogs } from '@/api'
import type { AuditLogItem } from '@/api/types'
import { useResourceRefresh } from '@/composables/useNotifications'
import { formatDateTime, truncate } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

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
    ElMessage.error(errorMessage(err, '操作失败'))
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

/** 时间线里展开的 payload（同一时刻只展开一条，避免长列表被多段 JSON 撑爆） */
const expandedId = ref<number | null>(null)

function togglePayload(id: number): void {
  expandedId.value = expandedId.value === id ? null : id
}

// 资源变更广播（400ms 去抖合并）：审计条目由合同/股票写操作产生，故一并订阅（本地过滤条件保留）
useResourceRefresh(['audit-logs', 'logs', 'contracts', 'stock'], load)

onMounted(() => void load())
</script>

<template>
  <div class="audit-log-page">
    <h1 class="page-title">审计流水</h1>

    <section class="panel audit-panel anim-fade-in-up">
      <div class="panel-head">
        <div class="panel-heading">
          <h2 class="section-title">审计流水</h2>
          <span class="count-tip value-num">共 {{ filteredItems.length }} 条</span>
        </div>
        <div class="toolbar">
          <el-input v-model="actionKeyword" placeholder="动作关键字" clearable style="width: 160px" />
          <el-input v-model="actorIdInput" placeholder="操作人 ID" clearable style="width: 120px" />
          <el-button @click="resetFilters">重置</el-button>
          <el-button :icon="Refresh" @click="load">刷新</el-button>
        </div>
      </div>

      <!-- 首屏骨架；实时重拉时保留时间线，避免闪白 -->
      <div v-if="loading && !filteredItems.length" class="audit-skeleton">
        <div v-for="i in 4" :key="i" class="skeleton skeleton-line" />
      </div>
      <el-empty v-else-if="!filteredItems.length" description="暂无审计记录" :image-size="72" />
      <ol v-else class="audit-timeline anim-stagger">
        <li v-for="row in filteredItems" :key="row.id" class="audit-item">
          <div class="audit-time value-num">{{ formatDateTime(row.occurredAt) }}</div>
          <span class="audit-node" aria-hidden="true"></span>
          <div class="audit-content">
            <div class="audit-line">
              <span class="audit-action">{{ row.action }}</span>
              <el-tag size="small" effect="plain">
                payload {{ Object.keys(row.payload ?? {}).length }} 项
              </el-tag>
              <span class="audit-actor">{{ row.actorUsername || row.actorId || '—' }}</span>
            </div>
            <div class="audit-meta">
              <span class="meta-item">对象：{{ row.target || '—' }}</span>
              <span class="meta-item mono" :title="row.traceId">
                Trace ID：{{ truncate(row.traceId, 18) }}
              </span>
            </div>
            <button type="button" class="payload-toggle pressable" @click="togglePayload(row.id)">
              {{ expandedId === row.id ? '收起 payload' : '查看 payload（JSON）' }}
            </button>
            <pre v-if="expandedId === row.id" class="json-pre">{{ prettyJson(row.payload) }}</pre>
          </div>
        </li>
      </ol>
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
  margin-bottom: 12px;
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

/* 筛选项集中在一条工具条里 */
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.audit-skeleton {
  padding: 8px 0;
}

/* ===== 审计时间线（流水按时间纵向排列，比宽表更符合“审计流水”的读法） ===== */
.audit-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}

.audit-item {
  position: relative;
  display: grid;
  grid-template-columns: 148px 16px minmax(0, 1fr);
  column-gap: 12px;
  padding: 10px 0;
}

/* 纵向连线：首尾各收到第一个圆点处，避免线条悬空 */
.audit-item::before {
  content: "";
  position: absolute;
  left: 168px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--color-border);
}

.audit-item:first-child::before {
  top: 21px;
}

.audit-item:last-child::before {
  bottom: auto;
  height: 21px;
}

.audit-time {
  padding-top: 3px;
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}

.audit-node {
  justify-self: center;
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.12);
  z-index: 1;
}

.audit-content {
  min-width: 0;
}

.audit-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.audit-action {
  font-size: var(--font-sm);
  font-weight: 700;
  color: var(--color-text-primary);
  word-break: break-all;
}

.audit-actor {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}

.audit-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 4px;
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}

.mono {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
}

.payload-toggle {
  margin-top: 6px;
  padding: 0;
  border: none;
  background: none;
  color: var(--color-primary);
  font-size: var(--font-xs);
  cursor: pointer;
}

.payload-toggle:hover {
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

/* 窄屏：时间线落回单列，隐藏连线与圆点 */
@media (max-width: 640px) {
  .audit-item {
    grid-template-columns: minmax(0, 1fr);
    row-gap: 4px;
  }
  .audit-item::before,
  .audit-node {
    display: none;
  }
}
</style>
