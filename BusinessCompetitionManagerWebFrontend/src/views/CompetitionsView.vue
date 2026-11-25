<script setup lang="ts">
// 比赛列表页：比赛卡片墙 + 创建比赛（系统超级管理员）+ 激活码加入比赛
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules, UploadFile } from 'element-plus'
import * as api from '@/api'
import { uploadFile as uploadFileApi } from '@/api/filesApi'
import type { Competition, School } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useAuthedImage } from '@/composables/useAuthedImage'
import JoinTicketOverlay from '@/components/competition/JoinTicketOverlay.vue'

const router = useRouter()
const auth = useAuthStore()

const competitions = ref<Competition[]>([])
const loading = ref(false)
// 错误就地提示（保留 ElMessage 兜底，页面顶部同时给出可重试提示）
const errorText = ref('')

// ---------- 创建比赛（系统超级管理员） ----------
const showCreate = ref(false)
const creating = ref(false)
const createRef = ref<FormInstance>()
const createForm = ref({
  name: '',
  code: '',
  coverImage: '',
  ticketImage: '',
  hostSchoolIds: [] as number[],
  location: '',
})
const coverUploading = ref(false)
// 受保护文件需带 token 拉取后再预览（<img> 不会带 Authorization）
const coverPreviewSrc = useAuthedImage(() => createForm.value.coverImage)
const ticketImagePreviewSrc = useAuthedImage(() => createForm.value.ticketImage)
const ticketImageUploading = ref(false)

/** 纪念票图：铺在加入比赛时入场券的左侧主票上 */
async function onTicketImageSelected(file: UploadFile): Promise<void> {
  const raw = file.raw
  if (!raw) return
  if (!/^image\//.test(raw.type)) {
    ElMessage.warning('请选择图片文件')
    return
  }
  ticketImageUploading.value = true
  try {
    const uploaded = await uploadFileApi(raw)
    createForm.value.ticketImage = uploaded.url
    ElMessage.success('纪念票图已上传')
  } catch (err) {
    ElMessage.error(errorMessage(err, '上传失败'))
  } finally {
    ticketImageUploading.value = false
  }
}

/** 封面图：上传图片到文件服务，回填 url */
async function onCoverSelected(file: UploadFile): Promise<void> {
  const raw = file.raw
  if (!raw) return
  if (!/^image\//.test(raw.type)) {
    ElMessage.warning('请选择图片文件')
    return
  }
  coverUploading.value = true
  try {
    const uploaded = await uploadFileApi(raw)
    createForm.value.coverImage = uploaded.url
    ElMessage.success('封面图已上传')
  } catch (err) {
    ElMessage.error(errorMessage(err, '上传失败'))
  } finally {
    coverUploading.value = false
  }
}

const createRules: FormRules = {
  name: [{ required: true, message: '请输入比赛名称', trigger: 'blur' }],
  hostSchoolIds: [
    { required: true, type: 'array', min: 1, message: '请选择至少一所办赛学校', trigger: 'change' },
  ],
}
const schools = ref<School[]>([])
const schoolsLoading = ref(false)

// ---------- 激活码加入比赛 ----------
const showJoin = ref(false)
const joining = ref(false)
const joinFormRef = ref<FormInstance>()
const joinForm = reactive({ code: '' })
const joinRules: FormRules = {
  code: [{ required: true, message: '请输入激活码', trigger: 'blur' }],
}

/** 加入成功后的入场券（全屏动画）；确认/跳过后再进入比赛 */
const ticketInfo = ref<{
  competitionId: number
  competitionName: string
  identityLabel: string
  userName: string
  joinedAt: string
  ticketImage?: string
  ticketNo?: number | null
} | null>(null)

function enterFromTicket(): void {
  const info = ticketInfo.value
  ticketInfo.value = null
  if (!info) return
  auth.selectCompetition(info.competitionId)
  void router.push(`/competitions/${info.competitionId}/dashboard`)
}

function skipTicket(): void {
  ticketInfo.value = null
}

/** 状态标签配色（按生命周期链区分） */
function statusTagType(status: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  switch (status) {
    case 'ENROLLING':
      return 'warning'
    case 'RUNNING':
      return 'success'
    case 'SETTLING':
      return 'warning'
    case 'CLOSED':
      return 'info'
    default:
      return 'info'
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    competitions.value = await api.getCompetitions()
    errorText.value = ''
  } catch (err) {
    const message = errorMessage(err, '加载失败')
    errorText.value = message
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}

// 实时刷新：比赛 / 学校 变更广播（400ms 去抖合并）后重拉列表，保留当前筛选与滚动状态
useResourceRefresh(['competitions', 'schools'], load)

/** 打开创建弹窗前加载学校选项 */
async function openCreate(): Promise<void> {
  showCreate.value = true
  schoolsLoading.value = true
  try {
    schools.value = await api.getSchools()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    schoolsLoading.value = false
  }
}

async function submitCreate(): Promise<void> {
  try {
    await createRef.value?.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    await api.createCompetition({
      name: createForm.value.name.trim(),
      code: createForm.value.code.trim() || undefined,
      coverImage: createForm.value.coverImage.trim(),
      ticketImage: createForm.value.ticketImage.trim(),
      hostSchoolIds: createForm.value.hostSchoolIds,
      location: createForm.value.location.trim() || undefined,
    })
    ElMessage.success('比赛已创建')
    showCreate.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    creating.value = false
  }
}

/** 点击卡片：选中比赛上下文并进入仪表盘（详情仅超级管理员可见） */
function openCompetition(comp: Competition): void {
  auth.selectCompetition(comp.id)
  void router.push(`/competitions/${comp.id}/dashboard`)
}

async function submitJoin(): Promise<void> {
  try {
    await joinFormRef.value?.validate()
  } catch {
    return // 未填激活码：表单项就地报错（必填）
  }
  const code = joinForm.code.trim()
  joining.value = true
  try {
    const result = await api.redeemInvite(code)
    showJoin.value = false
    joinForm.code = ''
    // 刷新列表与我的身份
    await Promise.all([load(), auth.fetchMe()])
    // 加入成功 → 播放入场券动画（比赛名/身份/盖章）
    const joinedCompetition = competitions.value.find((item) => item.id === result.competitionId)
    ticketInfo.value = {
      competitionId: result.competitionId,
      competitionName: result.competitionName,
      identityLabel: result.identityLabel,
      userName: auth.user?.displayName || auth.user?.username || '',
      joinedAt: new Date().toISOString(),
      ticketImage: joinedCompetition?.ticketImage ?? '',
      ticketNo: result.ticketNo ?? null,
    }
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    joining.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="competitions-page page">
    <!-- 标题栏 -->
    <PageHeader title="比赛列表" :hint="competitions.length ? `共 ${competitions.length} 场` : ''">
      <template #actions>
        <el-button @click="showJoin = true">
          <el-icon><Key /></el-icon>
          <span>激活码加入比赛</span>
        </el-button>
        <el-button v-if="auth.isSuperuser" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>创建比赛</span>
        </el-button>
      </template>
    </PageHeader>

    <!-- 加载失败：就地提示 + 重试（不整页弹窗） -->
    <div v-if="errorText" class="notice notice--danger page-error" role="alert">
      <el-icon class="notice__icon"><WarningFilled /></el-icon>
      <span class="page-error-text">{{ errorText }}</span>
      <el-button size="small" class="page-error-retry" @click="load">重试</el-button>
    </div>

    <!-- 首屏骨架：与真实卡片同构，避免先空一下再跳出来 -->
    <div v-if="!competitions.length && loading" class="comp-grid">
      <div v-for="n in 6" :key="n" class="panel comp-skeleton">
        <div class="skeleton skeleton-line comp-skeleton-title"></div>
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-line"></div>
      </div>
    </div>
    <el-empty
      v-else-if="!competitions.length && !errorText"
      description="暂无可见的比赛，可用激活码加入"
     :image-size="72" />

    <!-- 比赛卡片墙：每卡突出「名称 + 状态 + 关键元信息 + 创建时间」 -->
    <div v-else-if="competitions.length" class="comp-grid anim-stagger">
      <el-card
        v-for="comp in competitions"
        :key="comp.id"
        class="comp-card hover-lift pressable"
        shadow="hover"
        role="link"
        tabindex="0"
        @click="openCompetition(comp)"
        @keydown.enter="openCompetition(comp)"
      >
        <div class="comp-card-head">
          <h3 class="comp-name" :title="comp.name">{{ comp.name }}</h3>
          <el-tag :type="statusTagType(comp.status)" size="small" class="comp-status">
            {{ comp.statusLabel }}
          </el-tag>
        </div>

        <div class="comp-meta">
          <div class="comp-meta-row">
            <el-icon class="comp-meta-icon"><Ticket /></el-icon>
            <span class="comp-meta-label">编码</span>
            <span class="comp-meta-value">{{ comp.code || '—' }}</span>
          </div>
          <div class="comp-meta-row">
            <el-icon class="comp-meta-icon"><Location /></el-icon>
            <span class="comp-meta-label">地点</span>
            <span class="comp-meta-value">{{ comp.location || '—' }}</span>
          </div>
          <div class="comp-meta-row">
            <el-icon class="comp-meta-icon"><School /></el-icon>
            <span class="comp-meta-label">办赛学校</span>
            <span class="comp-meta-value">{{ comp.hostSchoolNames?.join('、') || '—' }}</span>
          </div>
        </div>

        <div class="comp-card-foot">
          <span class="comp-meta-label">创建时间</span>
          <span class="comp-time value-num">{{ formatDateTime(comp.createdAt) }}</span>
        </div>
      </el-card>
    </div>

    <!-- 创建比赛弹窗 -->
    <el-dialog v-model="showCreate" title="创建比赛" width="560px" destroy-on-close>
      <el-form
        ref="createRef"
        :model="createForm"
        :rules="createRules"
        label-width="96px"
        @submit.prevent
      >
        <el-form-item label="比赛名称" prop="name">
          <el-input v-model="createForm.name" placeholder="例如：2025 春季商赛" maxlength="100" />
        </el-form-item>
        <el-form-item label="比赛编码">
          <el-input v-model="createForm.code" placeholder="可选，留空则自动生成" />
        </el-form-item>
        <el-form-item label="纪念票图">
          <div class="cover-field">
            <div class="cover-actions">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                accept="image/*"
                :on-change="onTicketImageSelected"
              >
                <el-button :loading="ticketImageUploading">
                  {{ createForm.ticketImage ? '重新上传' : '上传图片' }}
                </el-button>
              </el-upload>
              <el-button
                v-if="createForm.ticketImage"
                link
                type="danger"
                @click="createForm.ticketImage = ''"
                >移除</el-button
              >
            </div>
            <img
              v-if="ticketImagePreviewSrc"
              :src="ticketImagePreviewSrc"
              class="cover-preview"
              alt="纪念票图预览"
            />
            <p class="ticket-image-tip">这张图会铺在加入比赛时入场券的左侧主票上</p>
          </div>
        </el-form-item>
        <el-form-item label="封面图">
          <div class="cover-field">
            <div class="cover-actions">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                accept="image/*"
                :on-change="onCoverSelected"
              >
                <el-button :loading="coverUploading">
                  {{ createForm.coverImage ? '重新上传' : '上传图片' }}
                </el-button>
              </el-upload>
              <el-button
                v-if="createForm.coverImage"
                link
                type="danger"
                @click="createForm.coverImage = ''"
                >移除</el-button
              >
            </div>
            <img
              v-if="coverPreviewSrc"
              :src="coverPreviewSrc"
              class="cover-preview"
              alt="封面图预览"
            />
          </div>
        </el-form-item>
        <el-form-item label="办赛学校" prop="hostSchoolIds">
          <el-select
            v-model="createForm.hostSchoolIds"
            multiple
            :loading="schoolsLoading"
            filterable
            clearable
            placeholder="必选，至少选择一所办赛学校"
            style="width: 100%"
          >
            <el-option
              v-for="s in schools"
              :key="s.id"
              :label="s.name"
              :value="s.id"
            >
              <span>{{ s.name }}</span>
              <span class="school-region">{{ s.region }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="地点">
          <el-input v-model="createForm.location" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 激活码加入比赛弹窗 -->
    <el-dialog v-model="showJoin" title="激活码加入比赛" width="420px" destroy-on-close>
      <el-form
        ref="joinFormRef"
        :model="joinForm"
        :rules="joinRules"
        label-width="96px"
        @submit.prevent
      >
        <el-form-item label="激活码" prop="code">
          <el-input
            v-model="joinForm.code"
            placeholder="请输入激活码"
            clearable
            @keyup.enter="submitJoin"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showJoin = false">取消</el-button>
        <el-button type="primary" :loading="joining" @click="submitJoin">加入</el-button>
      </template>
    </el-dialog>

    <JoinTicketOverlay
      v-if="ticketInfo"
      v-bind="ticketInfo"
      :ticket-image="ticketInfo.ticketImage"
      @enter="enterFromTicket"
      @skip="skipTicket"
    />
  </div>
</template>

<style scoped lang="scss">
.page-toolbar {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
  row-gap: 10px;
  margin-bottom: 16px;
}

.page-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex: 1 1 auto;
  min-width: 0;
}

/* 与全局 .page-title 的 16px 下边距合并为标题栏自身的间距 */
.page-heading .page-title {
  margin-bottom: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page-count {
  flex-shrink: 0;
  font-size: var(--font-sm);
  color: var(--color-text-tertiary);
}

.page-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
  margin-left: auto;
}

/* 错误就地提示：同一行给原因与重试，避免只弹 toast 后页面空着 */
.page-error {
  align-items: center;
  margin-bottom: 16px;
}

.page-error-text {
  flex: 1 1 auto;
  min-width: 0;
}

.page-error-retry {
  flex-shrink: 0;
}

.comp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.comp-skeleton {
  padding: 20px;
}

.comp-skeleton .comp-skeleton-title {
  width: 70%;
  height: 16px;
  margin-bottom: 16px;
}

.comp-skeleton .skeleton-line:last-child {
  width: 40%;
}

.comp-card {
  display: flex;
  flex-direction: column;
  cursor: pointer;
}

/* 交错入场只在首帧做位移：结束后交还 transform，悬停轻抬/按下微缩才生效 */
.comp-grid .comp-card {
  animation-fill-mode: backwards;
}

.comp-card-head {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}

.comp-status {
  flex-shrink: 0;
}

.comp-name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--font-lg);
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text-primary);
  /* 长比赛名最多两行，状态标签始终可见 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.comp-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1 1 auto;
}

.comp-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: var(--font-sm);
}

.comp-meta-icon {
  flex-shrink: 0;
  color: var(--color-text-tertiary);
}

.comp-meta-label {
  flex-shrink: 0;
  color: var(--color-text-tertiary);
}

.comp-meta-value {
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.comp-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px solid var(--color-border);
  font-size: var(--font-xs);
}

.comp-time {
  color: var(--color-text-secondary);
}

.school-region {
  float: right;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}

/* 封面上传 */
.cover-field {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.cover-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ticket-image-tip {
  margin: 6px 0 0;
  color: var(--color-text-tertiary);
  font-size: 12px;
  line-height: 1.4;
}

.cover-preview {
  display: block;
  width: 100%;
  max-width: 220px;
  height: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
</style>
