<template>
  <el-dialog
    v-model="visible"
    width="560px"
    top="8vh"
    class="update-log-dialog"
    :close-on-click-modal="false"
    append-to-body
    @closed="markRead"
  >
    <template #header>
      <div class="update-head">
        <div class="update-title-row">
          <span class="update-title">系统已更新</span>
          <el-tag size="small" effect="plain">{{ log?.version }}</el-tag>
        </div>
        <p class="update-sub">{{ log?.title }}</p>
        <p class="update-meta">{{ formatDateTime(log?.publishedAt) }}</p>
      </div>
    </template>

    <div class="update-body">{{ log?.content }}</div>

    <template #footer>
      <el-button type="primary" @click="visible = false">我知道了</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getLatestUpdateLog, markUpdateLogRead } from '@/api'
import type { UpdateLog } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const visible = ref(false)
const log = ref<UpdateLog | null>(null)
let pendingId = 0

async function markRead(): Promise<void> {
  if (!pendingId) return
  const id = pendingId
  pendingId = 0
  try {
    await markUpdateLogRead(id)
  } catch {
    // 标记失败不打扰用户；下次进入会再提示一次
  }
}

onMounted(async () => {
  try {
    const result = await getLatestUpdateLog()
    if (!result.shouldShow || !result.log) return
    log.value = result.log
    pendingId = result.log.id
    visible.value = true
  } catch {
    // 更新日志接口不可用时静默，不影响主流程
  }
})
</script>

<style scoped>
.update-head {
  padding-right: 20px;
}

.update-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.update-title {
  color: var(--color-text-primary);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.update-sub {
  margin: 8px 0 0;
  color: var(--color-text-primary);
  font-size: 14px;
  font-weight: 500;
}

.update-meta {
  margin: 4px 0 0;
  color: var(--color-text-tertiary);
  font-size: 12px;
}

.update-body {
  max-height: 52vh;
  overflow-y: auto;
  padding: 4px 2px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
