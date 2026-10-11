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

const router = useRouter()
const auth = useAuthStore()

const competitions = ref<Competition[]>([])
const loading = ref(false)

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
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    loading.value = false
  }
}

/** 打开创建弹窗前加载学校选项 */
async function openCreate(): Promise<void> {
  showCreate.value = true
  schoolsLoading.value = true
  try {
    schools.value = await api.getSchools()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
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
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
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
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
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
      <h2 class="page-title">比赛列表</h2>
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

    <!-- 加载 / 空态 -->
    <div v-if="loading" v-loading="loading" class="comp-grid-loading"></div>
    <el-empty v-else-if="competitions.length === 0" description="暂无可见的比赛，可用激活码加入" />

    <!-- 比赛卡片墙 -->
    <div v-else class="comp-grid">
      <el-card
        v-for="comp in competitions"
        :key="comp.id"
        class="comp-card"
        shadow="hover"
        tabindex="0"
        @click="openCompetition(comp)"
        @keydown.enter="openCompetition(comp)"
      >
        <div class="comp-card-head">
          <h3 class="comp-name">{{ comp.name }}</h3>
          <el-tag :type="statusTagType(comp.status)" size="small">{{ comp.statusLabel }}</el-tag>
        </div>
        <div class="comp-row">
          <span class="comp-label">编码</span>
          <span class="comp-value">{{ comp.code || '—' }}</span>
        </div>
        <div class="comp-row">
          <span class="comp-label">地点</span>
          <span class="comp-value">{{ comp.location || '—' }}</span>
        </div>
        <div class="comp-row">
          <span class="comp-label">办赛学校</span>
          <span class="comp-value">{{ comp.hostSchoolName || '—' }}</span>
        </div>
        <div class="comp-row">
          <span class="comp-label">创建时间</span>
          <span class="comp-value">{{ formatDateTime(comp.createdAt) }}</span>
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
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.page-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.comp-grid-loading {
  min-height: 240px;
  border-radius: var(--radius-md);
}

.comp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.comp-card {
  cursor: pointer;
  outline: none;
  animation: fade-in-up var(--dur-slow) var(--ease-out-expo) both;

  &:focus-visible {
    box-shadow: 0 0 0 3px rgba(var(--color-primary-rgb), 0.2);
  }
}

.comp-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.comp-name {
  font-size: var(--font-lg);
  font-weight: 600;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.comp-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  line-height: 1.9;
  font-size: var(--font-sm);
}

.comp-label {
  flex-shrink: 0;
  color: var(--color-text-tertiary);
}

.comp-value {
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.school-region {
  float: right;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}
</style>
