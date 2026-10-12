<script setup lang="ts">
// 站内信（系统级，独立于比赛）：收件箱 / 发件箱 / 写站内信（收件人=比赛+个人混合多选）
// 口径：个人发送自由；「按比赛（全员）」批量=公告，仅超级管理员可发。
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Check, EditPen, Refresh } from '@element-plus/icons-vue'
import {
  getAddressBook,
  getInbox,
  getSentInmails,
  readAllInmails,
  readInmail,
  sendInmail,
} from '@/api'
import type { AddressBook, InmailKind, InmailMessage, SendInmailPayload } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

const auth = useAuthStore()
const router = useRouter()
const activeTab = ref<'inbox' | 'sent'>('inbox')

// ---------- 收件箱 ----------
const inbox = ref<InmailMessage[]>([])
const unreadCount = ref(0)
const inboxTotal = ref(0)
const inboxLoading = ref(false)
const unreadOnly = ref(false)
const kindFilter = ref<InmailKind | ''>('')

const KIND_META: Record<InmailKind, { label: string; type: 'primary' | 'warning' | 'info' }> = {
  PERSONAL: { label: '站内信', type: 'primary' },
  ANNOUNCE: { label: '公告', type: 'warning' },
  SYSTEM: { label: '系统通知', type: 'info' },
}

async function loadInbox(): Promise<void> {
  inboxLoading.value = true
  try {
    const page = await getInbox({
      unread: unreadOnly.value,
      kind: kindFilter.value || undefined,
      limit: 100,
    })
    inbox.value = page.items
    inboxTotal.value = page.total
    unreadCount.value = page.unread
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    inboxLoading.value = false
  }
}

async function markRead(item: InmailMessage & { recipientId?: number }): Promise<void> {
  if (item.readAt || item.recipientId == null) return
  try {
    await readInmail(item.recipientId) // 收件人记录 id（MessageRecipient）
    item.readAt = new Date().toISOString()
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

async function markAllRead(): Promise<void> {
  try {
    const result = await readAllInmails()
    ElMessage.success(`已标记 ${result.updated} 条为已读`)
    await loadInbox()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

function openSource(item: InmailMessage): void {
  const payload = item.payload || {}
  const link = typeof payload.link === 'string' ? payload.link : ''
  if (link) {
    void router.push(link)
    return
  }
  // 只接受有效数字 id（系统通知的 competitionId 可能为空，防 /competitions/undefined）
  const cid = Number(item.competitionId)
  if (Number.isInteger(cid) && cid > 0) {
    void router.push(`/competitions/${cid}`)
  }
}

const hasSource = (item: InmailMessage): boolean =>
  Boolean(typeof item.payload?.link === 'string' && item.payload.link) || Boolean(item.competitionId)

/** 发件箱阅读比（已读/总数） */
const readRatio = (item: InmailMessage): string => {
  const list = item.recipients ?? []
  return `${list.filter((r) => r.readAt).length}/${list.length}`
}

const recipientCount = (item: InmailMessage): number => item.recipients?.length ?? 0

// ---------- 发件箱 ----------
const sent = ref<InmailMessage[]>([])
const sentLoading = ref(false)

async function loadSent(): Promise<void> {
  sentLoading.value = true
  try {
    sent.value = await getSentInmails()
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    sentLoading.value = false
  }
}

// ---------- 写站内信（收件人多选：比赛 + 个人） ----------
const composeVisible = ref(false)
const submitting = ref(false)
const addressBook = ref<AddressBook | null>(null)
const form = ref({ title: '', body: '' })
const selected = ref<string[]>([]) // 'comp-<id>' | 'user-<id>'

const canBulkSend = computed(() => auth.isSuperuser || auth.memberships.length > 0)

async function openCompose(): Promise<void> {
  composeVisible.value = true
  if (!addressBook.value) {
    try {
      addressBook.value = await getAddressBook()
    } catch (e) {
      ElMessage.error(errorMessage(e, '通讯录加载失败'))
    }
  }
}

const selectionSummary = computed(() => {
  const compIds = selected.value.filter((v) => v.startsWith('comp-'))
  const userIds = selected.value.filter((v) => v.startsWith('user-'))
  const parts: string[] = []
  if (compIds.length) parts.push(`${compIds.length} 个比赛（全员）`)
  if (userIds.length) parts.push(`${userIds.length} 位个人`)
  return parts.join(' + ') || '未选择'
})

async function submitCompose(): Promise<void> {
  if (!form.value.title.trim()) {
    ElMessage.warning('请填写标题')
    return
  }
  const competitionIds = selected.value
    .filter((v) => v.startsWith('comp-'))
    .map((v) => Number(v.slice(5)))
  const recipientUserIds = selected.value
    .filter((v) => v.startsWith('user-'))
    .map((v) => Number(v.slice(5)))
  if (!competitionIds.length && !recipientUserIds.length) {
    ElMessage.warning('请选择接收人（比赛或个人）')
    return
  }
  if (competitionIds.length && !auth.isSuperuser) {
    const allowed = new Set(
      auth.memberships
        .filter((m) => m.identity === 'COMP_SUPER_ADMIN')
        .map((m) => m.id),
    )
    if (competitionIds.some((cid) => !allowed.has(cid))) {
      ElMessage.error('按比赛发送（公告）需要你是该比赛的超级管理员（或系统超管）')
      return
    }
  }
  const payload: SendInmailPayload = {
    title: form.value.title.trim(),
    body: form.value.body,
    competitionIds,
    recipientUserIds,
  }
  submitting.value = true
  try {
    await sendInmail(payload)
    ElMessage.success('发送成功')
    composeVisible.value = false
    form.value = { title: '', body: '' }
    selected.value = []
    await loadSent()
  } catch (e) {
    ElMessage.error(errorMessage(e, '发送失败'))
  } finally {
    submitting.value = false
  }
}

// ---------- 初始化 ----------
async function switchTab(tab: 'inbox' | 'sent'): Promise<void> {
  activeTab.value = tab
  if (tab === 'inbox') await loadInbox()
  else await loadSent()
}

onMounted(() => {
  void loadInbox()
})
</script>

<template>
  <div class="messages-page">
    <div class="page-head">
      <h1 class="page-title">站内信</h1>
      <div class="head-actions">
        <el-button :icon="Refresh" @click="activeTab === 'inbox' ? loadInbox() : loadSent()">
          刷新
        </el-button>
        <el-button type="primary" :icon="EditPen" @click="openCompose">写站内信</el-button>
      </div>
    </div>

    <el-tabs :model-value="activeTab" @tab-change="(v: string) => switchTab(v as 'inbox' | 'sent')">
      <!-- ===== 收件箱 ===== -->
      <el-tab-pane name="inbox">
        <template #label>
          收件箱
          <el-badge v-if="unreadCount" :value="unreadCount" :max="99" class="inbox-badge" />
        </template>

        <div class="filter-row">
          <el-checkbox v-model="unreadOnly" @change="loadInbox">只看未读</el-checkbox>
          <el-select v-model="kindFilter" clearable placeholder="全部类型" class="kind-select" @change="loadInbox">
            <el-option label="站内信" value="PERSONAL" />
            <el-option label="公告" value="ANNOUNCE" />
            <el-option label="系统通知" value="SYSTEM" />
          </el-select>
          <el-button :icon="Check" @click="markAllRead">全部标记已读</el-button>
          <span class="total-tip">共 {{ inboxTotal }} 条</span>
        </div>

        <el-table v-loading="inboxLoading" :data="inbox" @row-click="markRead" class="mail-table">
          <el-table-column width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="KIND_META[row.kind as InmailKind]?.type ?? 'info'">
                {{ KIND_META[row.kind as InmailKind]?.label ?? row.kindLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="发件人" width="140">
            <template #default="{ row }">
              <span :class="{ unread: !row.readAt }">{{ row.senderName }}</span>
            </template>
          </el-table-column>
          <el-table-column label="标题 / 内容" min-width="320">
            <template #default="{ row }">
              <div class="mail-title" :class="{ unread: !row.readAt }">
                <span v-if="!row.readAt" class="dot" />{{ row.title }}
              </div>
              <div class="mail-body">{{ row.body }}</div>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
          </el-table-column>
          <el-table-column label="状态 / 操作" width="150">
            <template #default="{ row }">
              <el-tag v-if="row.readAt" size="small" type="info">已读</el-tag>
              <el-tag v-else size="small" type="danger">未读</el-tag>
              <el-button v-if="hasSource(row)" link type="primary" size="small" @click.stop="openSource(row)">
                查看来源
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!inboxLoading && !inbox.length" description="暂无消息" />
      </el-tab-pane>

      <!-- ===== 发件箱 ===== -->
      <el-tab-pane name="sent" label="发件箱">
        <el-table v-loading="sentLoading" :data="sent" class="mail-table">
          <el-table-column width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="KIND_META[row.kind as InmailKind]?.type ?? 'info'">
                {{ KIND_META[row.kind as InmailKind]?.label ?? row.kindLabel }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="标题 / 内容" min-width="300">
            <template #default="{ row }">
              <div class="mail-title">{{ row.title }}</div>
              <div class="mail-body">{{ row.body }}</div>
            </template>
          </el-table-column>
          <el-table-column label="收件人（已读/总数）" min-width="220">
            <template #default="{ row }">
              <el-tag v-for="r in (row.recipients ?? []).slice(0, 6)" :key="r.userId" size="small"
                      :type="r.readAt ? 'success' : 'info'" class="recipient-tag">
                {{ r.username }}
              </el-tag>
              <span v-if="recipientCount(row) > 6" class="more-tip">
                等 {{ recipientCount(row) }} 人
              </span>
              <span class="read-ratio">（{{ readRatio(row) }}）</span>
            </template>
          </el-table-column>
          <el-table-column label="发送时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!sentLoading && !sent.length" description="暂无发送记录" />
      </el-tab-pane>
    </el-tabs>

    <!-- ===== 写站内信 ===== -->
    <el-dialog v-model="composeVisible" title="写站内信" width="640px">
      <el-form label-width="80px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="消息标题" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.body" type="textarea" :rows="5" maxlength="2000" placeholder="消息内容" />
        </el-form-item>
        <el-form-item label="接收人" required>
          <el-select
            v-model="selected"
            multiple
            filterable
            clearable
            collapse-tags
            collapse-tags-tooltip
            :max-collapse-tags="4"
            placeholder="按比赛（全员）或个人多选"
            class="recipient-select"
          >
            <el-option-group v-if="addressBook?.competitions.length" label="按比赛（选中 = 该比赛全体成员）">
              <el-option
                v-for="comp in addressBook.competitions"
                :key="`comp-${comp.id}`"
                :label="`${comp.name}（${comp.memberCount} 人）`"
                :value="`comp-${comp.id}`"
              />
            </el-option-group>
            <el-option-group v-if="addressBook?.users.length" label="个人">
              <el-option
                v-for="user in addressBook.users"
                :key="`user-${user.id}`"
                :label="user.displayName ? `${user.displayName}（${user.username}）` : user.username"
                :value="`user-${user.id}`"
              />
            </el-option-group>
          </el-select>
          <div class="recipient-tip">
            当前选择：{{ selectionSummary }}。按比赛发送属于「公告」，仅超级管理员可用；发送时自动去重。
            <span v-if="!canBulkSend">（你的身份暂无批量发送权限，仅可发个人）</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="composeVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCompose">发送</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.messages-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.head-actions {
  display: flex;
  gap: 8px;
}
.inbox-badge {
  margin-left: 6px;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.kind-select {
  width: 160px;
}
.total-tip {
  color: var(--color-text-secondary);
  font-size: 13px;
  margin-left: auto;
}
.mail-table {
  cursor: pointer;
}
.mail-title {
  font-weight: 600;
  color: var(--color-text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.mail-title.unread,
.unread {
  color: var(--color-primary);
  font-weight: 600;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-danger, #ef4444);
  display: inline-block;
}
.mail-body {
  color: var(--color-text-secondary);
  font-size: 12px;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.recipient-tag {
  margin-right: 4px;
}
.more-tip {
  color: var(--color-text-tertiary);
  font-size: 12px;
}
.read-ratio {
  color: var(--color-text-secondary);
  font-size: 12px;
}
.recipient-select {
  width: 100%;
}
.recipient-tip {
  width: 100%;
  color: var(--color-text-secondary);
  font-size: 12px;
  line-height: 1.6;
  margin-top: 4px;
}
</style>
