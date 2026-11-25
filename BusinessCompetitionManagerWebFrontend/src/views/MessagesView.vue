<script setup lang="ts">
// 站内信（系统级，独立于比赛）：收件箱 / 发件箱 / 写站内信（收件人=比赛+个人混合多选）
// 口径：个人发送自由；「按比赛（全员）」批量=公告，仅超级管理员可发。
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
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
import { uploadMessageImage } from '@/api/filesApi'
import type { AddressBook, InmailKind, InmailMessage, SendInmailPayload } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { useNotifications, useResourceRefresh } from '@/composables/useNotifications'

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
    ElMessage.success(`消息已标记 ${result.updated} 条为已读`)
    await loadInbox()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

/** 消息来源链接：优先用后端给的 link，其次按 payload 里的业务对象拼出页面地址 */
function sourceLink(item: InmailMessage): string {
  const payload = item.payload || {}
  const raw = typeof payload.link === 'string' ? payload.link.trim() : ''
  if (raw.startsWith('/')) return raw

  // 只接受有效数字 id（系统通知的 competitionId 可能为空，防 /competitions/undefined）
  const cid = Number(item.competitionId)
  if (!Number.isInteger(cid) || cid <= 0) return ''

  // 合同类通知：直接落到那张合同的详情页，而不是比赛仪表盘
  const contractId = Number(payload.contractId)
  if (Number.isInteger(contractId) && contractId > 0) {
    return `/competitions/${cid}/contracts/${contractId}`
  }
  return `/competitions/${cid}/dashboard`
}

function openSource(item: InmailMessage): void {
  const link = sourceLink(item)
  if (link) void router.push(link)
}

const hasSource = (item: InmailMessage): boolean => Boolean(sourceLink(item))

// ---------- 消息详情（抽屉：正文不再被列表的 2 行截断） ----------
const detailVisible = ref(false)
const detailItem = ref<InmailMessage | null>(null)

function openMessage(item: InmailMessage): void {
  detailItem.value = item
  detailVisible.value = true
  void markRead(item)
}

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

/** 实时重拉：收件箱 + 发件箱（保留当前页签与筛选条件） */
async function load(): Promise<void> {
  await Promise.all([loadInbox(), loadSent()])
}

// ---------- 写站内信（收件人多选：比赛 + 个人） ----------
const composeVisible = ref(false)
const submitting = ref(false)
const addressBook = ref<AddressBook | null>(null)
const form = ref({ title: '', body: '' })
const selected = ref<string[]>([]) // 'comp-<id>' | 'user-<id>'

// ---------- 图片附件（最多 9 张，随消息 payload.images 提交） ----------
const MAX_IMAGES = 9
const images = ref<string[]>([])
const imageUploading = ref(false)
const imageFileInput = ref<HTMLInputElement | null>(null)

function pickImages(): void {
  imageFileInput.value?.click()
}

/** 选择图片并逐张上传（调 uploadMessageImage），收集返回 url 到 images。 */
async function onImagesSelected(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = '' // 允许重复选择同一文件
  if (!files.length) return
  const remain = MAX_IMAGES - images.value.length
  if (remain <= 0) {
    ElMessage.warning(`最多上传 ${MAX_IMAGES} 张图片`)
    return
  }
  const accepted = files.slice(0, remain)
  if (files.length > remain) {
    ElMessage.warning(`最多上传 ${MAX_IMAGES} 张图片，已忽略多出的 ${files.length - remain} 张`)
  }
  imageUploading.value = true
  try {
    for (const file of accepted) {
      const { url } = await uploadMessageImage(file)
      images.value.push(url)
    }
  } catch (err) {
    ElMessage.error(errorMessage(err, '图片上传失败'))
  } finally {
    imageUploading.value = false
  }
}

function removeImage(index: number): void {
  images.value.splice(index, 1)
}

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

async function submitCompose(): Promise<void> {
  if (!form.value.title.trim()) {
    ElMessage.warning('请输入标题')
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
        .filter((m) => m.identity === 'ADMIN')
        .map((m) => m.id),
    )
    if (competitionIds.some((cid) => !allowed.has(cid))) {
      ElMessage.warning('按比赛发送公告需要你是该比赛的管理员或超级管理员')
      return
    }
  }
  // 图片 url 收集为 payload.images 随消息提交（payload 结构以页面现状为准，最小侵入）
  const payload: SendInmailPayload & { images: string[] } = {
    title: form.value.title.trim(),
    body: form.value.body,
    competitionIds,
    recipientUserIds,
    images: [...images.value],
  }
  submitting.value = true
  try {
    await sendInmail(payload)
    ElMessage.success('消息已发送')
    composeVisible.value = false
    form.value = { title: '', body: '' }
    selected.value = []
    images.value = []
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

// 实时站内信：新消息走 WebSocket notification 帧；已读状态等资源变更走 messages 事件
useNotifications((message) => {
  if (message.type === 'notification') void load()
})
useResourceRefresh(['messages'], () => {
  void load()
})
</script>

<template>
  <div class="messages-page page">
    <div class="page-head">
      <PageHeader title="消息中心">
        <template #actions>
          <el-button :icon="Refresh" @click="activeTab === 'inbox' ? loadInbox() : loadSent()">
            刷新
          </el-button>
          <el-button type="primary" :icon="EditPen" @click="openCompose">写消息</el-button>
        </template>
      </PageHeader>
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

        <!-- 首屏骨架；实时重拉时保留列表，避免闪白 -->
        <div v-if="inboxLoading && !inbox.length" class="mail-skeleton">
          <div v-for="i in 4" :key="i" class="skeleton mail-skeleton-row" />
        </div>
        <div v-else-if="inbox.length" class="mail-list mail-list--inbox anim-stagger">
          <article
            v-for="row in inbox"
            :key="row.id"
            class="mail-item"
            :class="{ 'is-unread': !row.readAt }"
            role="button"
            tabindex="0"
            @click="openMessage(row)"
            @keydown.enter.prevent="openMessage(row)"
          >
            <div class="mail-kind">
              <el-tag size="small" :type="KIND_META[row.kind as InmailKind]?.type ?? 'info'">
                {{ KIND_META[row.kind as InmailKind]?.label ?? row.kindLabel }}
              </el-tag>
            </div>
            <div class="mail-main">
              <div class="mail-title" :class="{ unread: !row.readAt }">
                <span v-if="!row.readAt" class="dot" />{{ row.title }}
              </div>
              <div class="mail-body">{{ row.body }}</div>
            </div>
            <div class="mail-side">
              <span class="mail-sender">{{ row.senderName }}</span>
              <span class="mail-time value-num">{{ formatDateTime(row.createdAt) }}</span>
              <el-tag v-if="row.readAt" size="small" type="info" effect="plain">已读</el-tag>
              <el-tag v-else size="small" type="danger" effect="plain">未读</el-tag>
              <el-button
                v-if="hasSource(row)"
                link
                type="primary"
                size="small"
                class="mail-source"
                @click.stop="openSource(row)"
              >
                查看来源
              </el-button>
            </div>
          </article>
        </div>
        <el-empty v-else description="暂无消息"  :image-size="72" />
      </el-tab-pane>

      <!-- ===== 发件箱 ===== -->
      <el-tab-pane name="sent" label="发件箱">
        <div v-if="sentLoading && !sent.length" class="mail-skeleton">
          <div v-for="i in 4" :key="i" class="skeleton mail-skeleton-row" />
        </div>
        <div v-else-if="sent.length" class="mail-list anim-stagger">
          <article v-for="row in sent" :key="row.id" class="mail-item">
            <div class="mail-kind">
              <el-tag size="small" :type="KIND_META[row.kind as InmailKind]?.type ?? 'info'">
                {{ KIND_META[row.kind as InmailKind]?.label ?? row.kindLabel }}
              </el-tag>
            </div>
            <div class="mail-main">
              <div class="mail-title">{{ row.title }}</div>
              <div class="mail-body">{{ row.body }}</div>
              <div class="mail-recipients">
                <span class="mail-label">收件人（已读/总数）</span>
                <el-tag
                  v-for="r in (row.recipients ?? []).slice(0, 6)"
                  :key="r.userId"
                  size="small"
                  :type="r.readAt ? 'success' : 'info'"
                  class="recipient-tag"
                >
                  {{ r.username }}
                </el-tag>
                <span v-if="recipientCount(row) > 6" class="more-tip">
                  等 {{ recipientCount(row) }} 人
                </span>
                <span class="read-ratio">（{{ readRatio(row) }}）</span>
              </div>
            </div>
            <div class="mail-side">
              <span class="mail-time value-num">{{ formatDateTime(row.createdAt) }}</span>
            </div>
          </article>
        </div>
        <el-empty v-else description="暂无发送记录"  :image-size="72" />
      </el-tab-pane>
    </el-tabs>

    <!-- ===== 写站内信 ===== -->
    <el-dialog v-model="composeVisible" title="写站内信" width="720px">
      <el-form label-width="96px">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="消息标题" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.body" type="textarea" :rows="5" maxlength="2000" placeholder="消息内容" />
        </el-form-item>
        <el-form-item label="图片">
          <div v-loading="imageUploading" class="image-uploader">
            <div v-for="(img, idx) in images" :key="img" class="image-thumb">
              <img :src="img" class="thumb-img" alt="消息图片" />
              <button type="button" class="thumb-remove" title="删除" @click="removeImage(idx)">×</button>
            </div>
            <button
              v-if="images.length < MAX_IMAGES"
              type="button"
              class="image-add"
              title="上传图片"
              @click="pickImages"
            >
              ＋
            </button>
          </div>
          <input
            ref="imageFileInput"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            multiple
            style="display: none"
            @change="onImagesSelected"
          />
          <div class="image-tip">最多 9 张，单张 ≤5MB（png/jpg/jpeg/gif/webp）</div>
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
            选中比赛＝发全员（仅超级管理员）
            <span v-if="!canBulkSend">；当前身份仅可发个人</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="composeVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCompose">发送</el-button>
      </template>
    </el-dialog>

    <!-- ===== 消息详情（抽屉，不打断列表上下文） ===== -->
    <el-drawer v-model="detailVisible" title="消息详情" size="min(420px, 92vw)" append-to-body>
      <div v-if="detailItem" class="detail">
        <div class="detail-head">
          <el-tag size="small" :type="KIND_META[detailItem.kind]?.type ?? 'info'">
            {{ KIND_META[detailItem.kind]?.label ?? detailItem.kindLabel }}
          </el-tag>
          <span class="detail-time value-num">{{ formatDateTime(detailItem.createdAt) }}</span>
        </div>
        <h3 class="detail-title">{{ detailItem.title }}</h3>
        <div class="detail-sender">发件人：{{ detailItem.senderName }}</div>
        <div class="detail-body">{{ detailItem.body }}</div>
        <el-button
          v-if="hasSource(detailItem)"
          link
          type="primary"
          @click="openSource(detailItem)"
        >
          查看来源
        </el-button>
      </div>
    </el-drawer>
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
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
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
/* ===== 消息列表（看板式行）：类型 / 标题摘要 / 发件人与时间三栏 ===== */
.mail-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mail-skeleton-row {
  height: 84px;
}
.mail-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mail-item {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr) 200px;
  gap: 14px;
  align-items: start;
  padding: 12px 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-left: 3px solid transparent;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
  transition:
    background-color var(--dur-fast) var(--ease-standard),
    border-color var(--dur-fast) var(--ease-standard),
    box-shadow var(--dur-fast) var(--ease-standard);
}
/* 未读：左侧品牌色标记 + 标题加重，语义一眼可辨 */
.mail-item.is-unread {
  border-left-color: var(--color-primary);
}
.mail-list--inbox .mail-item {
  cursor: pointer;
}
.mail-item:hover {
  background: var(--color-surface-2);
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
}
/* 悬停时保留未读标记（否则 border-color 简写会把左侧色条覆盖掉） */
.mail-item.is-unread:hover {
  border-left-color: var(--color-primary);
}
.mail-item:focus-visible {
  outline: 2px solid rgba(var(--color-primary-rgb), 0.55);
  outline-offset: 2px;
}
.mail-kind {
  padding-top: 1px;
}
.mail-main {
  min-width: 0;
}
.mail-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  min-width: 0;
}
.mail-sender {
  max-width: 100%;
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mail-time {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}
.mail-recipients {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 6px;
}
.mail-label {
  margin-right: 2px;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
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
  background: var(--color-danger);
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
/* 图片附件（缩略图 + 删除 + 添加） */
.image-uploader {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
  min-height: 32px;
}
.image-thumb {
  position: relative;
  width: 72px;
  height: 72px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  overflow: hidden;
}
.thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.thumb-remove {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
}
.image-add {
  width: 72px;
  height: 72px;
  border: 1px dashed var(--color-border);
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-tertiary, var(--color-text-tertiary));
  font-size: 20px;
  cursor: pointer;
}
.image-add:hover {
  color: var(--color-primary, var(--color-primary));
  border-color: var(--color-primary, var(--color-primary));
}
.image-tip {
  width: 100%;
  color: var(--color-text-tertiary, var(--color-text-tertiary));
  font-size: 12px;
  margin-top: 4px;
}

/* ===== 消息详情抽屉 ===== */
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.detail-time {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}
.detail-title {
  margin: 12px 0 6px;
  font-size: var(--font-lg);
  font-weight: 700;
  color: var(--color-text-primary);
}
.detail-sender {
  margin-bottom: 12px;
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.detail-body {
  margin-bottom: 16px;
  font-size: var(--font-base);
  line-height: 1.7;
  color: var(--color-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 窄屏：三栏收成一栏，发件人/时间/状态排到标题下方 */
@media (max-width: 640px) {
  .mail-item {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
  }
  .mail-side {
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
  }
  .mail-sender {
    margin-right: auto;
  }
}
</style>
