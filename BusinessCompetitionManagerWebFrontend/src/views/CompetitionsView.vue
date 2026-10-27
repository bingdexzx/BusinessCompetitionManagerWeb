<script setup lang="ts">
// 比赛列表页：比赛卡片墙 + 创建比赛（系统超管）+ 激活码加入比赛
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import * as api from '@/api'
import type { Competition, School } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { useResourceRefresh } from '@/composables/useNotifications'

const router = useRouter()
const auth = useAuthStore()

const competitions = ref<Competition[]>([])
const loading = ref(false)
// 错误就地提示（保留 ElMessage 兜底，页面顶部同时给出可重试提示）
const errorText = ref('')

// ---------- 创建比赛（系统超管） ----------
const showCreate = ref(false)
const creating = ref(false)
const createRef = ref<FormInstance>()
const createForm = ref({
  name: '',
  code: '',
  coverImage: '',
  hostSchoolId: null as number | null,
  location: '',
  staffingInfo: '',
})
const createRules: FormRules = {
  name: [{ required: true, message: '请填写比赛名称', trigger: 'blur' }],
}
const schools = ref<School[]>([])
const schoolsLoading = ref(false)

// ---------- 激活码加入比赛 ----------
const showJoin = ref(false)
const joining = ref(false)
const joinCode = ref('')

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
    const message = errorMessage(err, '操作失败')
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
    ElMessage.error(errorMessage(err, '操作失败'))
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
      coverImage: createForm.value.coverImage.trim() || undefined,
      hostSchoolId: createForm.value.hostSchoolId ?? undefined,
      location: createForm.value.location.trim() || undefined,
      staffingInfo: createForm.value.staffingInfo.trim() || undefined,
    })
    ElMessage.success('比赛创建成功')
    showCreate.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    creating.value = false
  }
}

/** 点击卡片：选中比赛上下文并进入详情 */
function openCompetition(comp: Competition): void {
  auth.selectCompetition(comp.id)
  void router.push(`/competitions/${comp.id}`)
}

async function submitJoin(): Promise<void> {
  const code = joinCode.value.trim()
  if (!code) {
    ElMessage.warning('请输入激活码')
    return
  }
  joining.value = true
  try {
    const result = await api.redeemInvite(code)
    ElMessage.success(`已加入「${result.competitionName}」，身份：${result.identityLabel}`)
    showJoin.value = false
    joinCode.value = ''
    // 刷新列表与我的身份
    await Promise.all([load(), auth.fetchMe()])
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    joining.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="competitions-page">
    <!-- 标题栏 -->
    <div class="page-toolbar">
      <div class="page-heading">
        <h2 class="page-title">比赛列表</h2>
        <span v-if="competitions.length" class="page-count">共 {{ competitions.length }} 场</span>
      </div>
      <div class="page-actions">
        <el-button @click="showJoin = true">
          <el-icon><Key /></el-icon>
          <span>激活码加入比赛</span>
        </el-button>
        <el-button v-if="auth.isSuperuser" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>创建比赛</span>
        </el-button>
      </div>
    </div>

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
    />

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
            <span class="comp-meta-value">{{ comp.hostSchoolName || '—' }}</span>
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
        <el-form-item label="封面图 URL">
          <el-input v-model="createForm.coverImage" placeholder="可选，https://…" />
        </el-form-item>
        <el-form-item label="办赛学校">
          <el-select
            v-model="createForm.hostSchoolId"
            :loading="schoolsLoading"
            filterable
            clearable
            placeholder="可选，输入搜索学校"
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
        <el-form-item label="人员安排">
          <el-input
            v-model="createForm.staffingInfo"
            type="textarea"
            :rows="3"
            placeholder="可选：工作人员 / 裁判 / 志愿者安排…"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 激活码加入比赛弹窗 -->
    <el-dialog v-model="showJoin" title="激活码加入比赛" width="420px" destroy-on-close>
      <el-form label-width="72px" @submit.prevent>
        <el-form-item label="激活码">
          <el-input
            v-model="joinCode"
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
</style>
