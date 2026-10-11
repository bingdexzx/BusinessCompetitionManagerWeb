<script setup lang="ts">
// 我的消息：跨比赛消息汇总，点击标记已读 / 一键全部已读
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Refresh } from '@element-plus/icons-vue'
import { getMyMessages, readMessage } from '@/api'
import type { MessageItem } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const messages = ref<MessageItem[]>([])
const loading = ref(false)
const filter = ref<'all' | 'unread'>('all')
const markingAll = ref(false)

const unreadCount = computed(() => messages.value.filter((m) => !m.readAt).length)

const visibleMessages = computed(() =>
  filter.value === 'unread' ? messages.value.filter((m) => !m.readAt) : messages.value,
)

async function load(): Promise<void> {
  loading.value = true
  try {
    messages.value = await getMyMessages()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    loading.value = false
  }
}

/** 点击消息：未读则标记已读并本地更新 */
async function onMessageClick(item: MessageItem): Promise<void> {
  if (item.readAt) return
  if (!item.competitionId) {
    ElMessage.error('该消息缺少比赛 ID，无法标记已读')
    return
  }
  try {
    await readMessage(item.competitionId, item.id)
    item.readAt = new Date().toISOString()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  }
}

/** 全部标记已读：逐条迭代未读消息 */
async function markAllRead(): Promise<void> {
  const unread = messages.value.filter((m) => !m.readAt)
  if (unread.length === 0) return
  markingAll.value = true
  let failed = 0
  for (const item of unread) {
    if (!item.competitionId) {
      failed += 1
      continue
    }
    try {
      await readMessage(item.competitionId, item.id)
      item.readAt = new Date().toISOString()
    } catch (err) {
      failed += 1
      ElMessage.error(err instanceof Error ? err.message : '操作失败')
    }
  }
  markingAll.value = false
  if (failed === 0) ElMessage.success(`已将 ${unread.length} 条消息标记为已读`)
}

onMounted(() => void load())
</script>

<template>
  <div class="messages-page">
    <h1 class="page-title">我的消息</h1>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">消息列表（未读 {{ unreadCount }} 条）</span>
          <div class="card-actions">
            <el-radio-group v-model="filter">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="unread">未读</el-radio-button>
            </el-radio-group>
            <el-button
              type="primary"
              plain
              :icon="Check"
              :loading="markingAll"
              :disabled="unreadCount === 0"
              @click="markAllRead"
            >
              全部标记已读
            </el-button>
            <el-button :icon="Refresh" @click="load">刷新</el-button>
          </div>
        </div>
      </template>

      <div v-loading="loading" class="message-list">
        <div
          v-for="item in visibleMessages"
          :key="item.id"
          class="message-item"
          :class="{ 'message-item--unread': !item.readAt }"
          @click="onMessageClick(item)"
        >
          <div class="message-head">
            <span class="unread-dot" :class="{ 'unread-dot--on': !item.readAt }"></span>
            <span class="message-title">{{ item.title }}</span>
            <el-tag v-if="item.competitionName" size="small" effect="plain" class="comp-tag">
              {{ item.competitionName }}
            </el-tag>
            <span class="message-time">{{ formatDateTime(item.createdAt) }}</span>
          </div>
          <div class="message-body">{{ item.body }}</div>
          <div class="message-foot">
            <el-tag v-if="item.readAt" size="small" type="info" effect="plain">
              已读 {{ formatDateTime(item.readAt) }}
            </el-tag>
            <el-tag v-else size="small" type="warning" effect="plain">未读</el-tag>
          </div>
        </div>

        <el-empty v-if="!loading && visibleMessages.length === 0" description="暂无消息" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.messages-page {
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
  align-items: center;
  flex-wrap: wrap;
}
.message-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}
.message-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  background: var(--color-surface);
  cursor: pointer;
  transition: box-shadow var(--dur-fast) var(--ease-standard),
    border-color var(--dur-fast) var(--ease-standard);
}
.message-item:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-strong);
}
.message-item--unread {
  background: var(--gradient-brand-soft);
  border-color: rgba(var(--color-primary-rgb), 0.25);
}
.message-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: transparent;
  flex-shrink: 0;
}
.unread-dot--on {
  background: var(--color-danger);
}
.message-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.comp-tag {
  flex-shrink: 0;
}
.message-time {
  margin-left: auto;
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}
.message-body {
  margin: 8px 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
  word-break: break-word;
}
.message-foot {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
