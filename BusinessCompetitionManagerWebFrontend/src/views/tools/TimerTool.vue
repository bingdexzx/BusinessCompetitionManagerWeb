<script setup lang="ts">
/**
 * 工具箱 - 计时器：按「名称 + 倒计时时长」创建，列表按秒倒数。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'

import PageHeader from '@/components/common/PageHeader.vue'
import { createTimer, deleteTimer, getTimers } from '@/api'
import type { CompetitionTimer } from '@/api/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ cid: string }>()

const timers = ref<CompetitionTimer[]>([])
const loading = ref(false)
const loaded = ref(false)
const saving = ref(false)
const showCreate = ref(false)
const formRef = ref<FormInstance>()
/** 时长输入：时 / 分 / 秒（分别填，避免用户算秒数） */
const form = ref({
  name: '',
  duration: { hours: 0, minutes: 0, seconds: 0 },
  note: '',
})
const rules: FormRules = {
  name: [
    { required: true, message: '请输入计时器名称', trigger: 'blur' },
    { max: 120, message: '名称最多 120 个字符', trigger: 'blur' },
  ],
  duration: [
    {
      required: true,
      validator: (_rule, _value, callback) => {
        if (formSeconds.value > 0) callback()
        else callback(new Error('请填写倒计时时长（时 / 分 / 秒不能同时为 0）'))
      },
      trigger: 'change',
    },
  ],
}
/** 每秒刷新的“现在”，用来算剩余时间 */
const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | null = null

const ordered = computed(() =>
  [...timers.value].sort(
    (a, b) => new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime(),
  ),
)

/** 剩余秒数：按「开始时间 + 时长」算，不受刷新影响 */
function remainingOf(timer: CompetitionTimer): number {
  const end = new Date(timer.targetAt).getTime()
  return Math.max(0, Math.round((end - now.value) / 1000))
}

/** 倒计时文案：X 天 HH:MM:SS；到点显示「已结束」 */
function countdownOf(timer: CompetitionTimer): string {
  const total = remainingOf(timer)
  if (total <= 0) return '已结束'
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const clock = [hours, minutes, seconds].map((n) => String(n).padStart(2, '0')).join(':')
  return days > 0 ? `${days} 天 ${clock}` : clock
}

function expired(timer: CompetitionTimer): boolean {
  return remainingOf(timer) <= 0
}

/** 总时长文案：1 小时 30 分 */
function durationText(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const parts: string[] = []
  if (days) parts.push(`${days} 天`)
  if (hours) parts.push(`${hours} 小时`)
  if (minutes) parts.push(`${minutes} 分`)
  if (secs || !parts.length) parts.push(`${secs} 秒`)
  return parts.join(' ')
}

const formSeconds = computed(() => {
  const { hours, minutes, seconds } = form.value.duration
  return (hours || 0) * 3600 + (minutes || 0) * 60 + (seconds || 0)
})

async function load(): Promise<void> {
  if (!props.cid) return
  loading.value = true
  try {
    timers.value = await getTimers(props.cid)
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载计时器失败'))
  } finally {
    loading.value = false
    loaded.value = true
  }
}

function openCreate(): void {
  form.value = { name: '', duration: { hours: 0, minutes: 0, seconds: 0 }, note: '' }
  showCreate.value = true
  void nextTick(() => formRef.value?.clearValidate())
}

async function submitCreate(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  const name = form.value.name.trim()
  saving.value = true
  try {
    const created = await createTimer(props.cid, {
      name,
      durationSeconds: formSeconds.value,
      note: form.value.note.trim() || undefined,
    })
    timers.value = [...timers.value, created]
    showCreate.value = false
    ElMessage.success('计时器已添加')
  } catch (e) {
    ElMessage.error(errorMessage(e, '添加计时器失败'))
  } finally {
    saving.value = false
  }
}

async function remove(timer: CompetitionTimer): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除计时器「${timer.name}」？`, '删除计时器', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteTimer(props.cid, timer.id)
    timers.value = timers.value.filter((item) => item.id !== timer.id)
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  }
}

onMounted(() => {
  void load()
  tick = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (tick) clearInterval(tick)
})
</script>

<template>
  <div class="tool-page page">
    <header class="tool-head">
      <PageHeader title="计时器">
        <template #actions>
          <div class="page-actions">
            <el-button :icon="Plus" type="primary" @click="openCreate">添加计时器</el-button>
          </div>
        </template>
      </PageHeader>
    </header>

    <el-card shadow="never" class="tool-card">
      <div v-if="loading && !loaded" class="timers-skeleton">
        <div v-for="n in 3" :key="n" class="skeleton skeleton-line" />
      </div>
      <el-empty
        v-else-if="!ordered.length"
        description="还没有计时器，点右上角「添加计时器」"
        :image-size="72"
      />
      <div v-else class="timer-list anim-stagger">
        <article
          v-for="timer in ordered"
          :key="timer.id"
          class="timer-row"
          :class="{ 'is-expired': expired(timer) }"
        >
          <div class="timer-main">
            <div class="timer-name">{{ timer.name }}</div>
            <div class="timer-meta">
              <span>时长：{{ durationText(timer.durationSeconds) }}</span>
              <span>开始：{{ formatDateTime(timer.startedAt) }}</span>
              <span v-if="timer.note" class="timer-note">{{ timer.note }}</span>
            </div>
          </div>
          <div class="timer-count">{{ countdownOf(timer) }}</div>
          <el-button :icon="Delete" link type="danger" @click="remove(timer)">删除</el-button>
        </article>
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="添加计时器" width="520px" append-to-body>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="96px"
        @submit.prevent="submitCreate"
      >
        <el-form-item label="名称" prop="name">
          <el-input
            v-model="form.name"
            maxlength="120"
            placeholder="请输入名称，例如：第一轮结算倒计时"
          />
        </el-form-item>
        <el-form-item label="倒计时" prop="duration" required>
          <div class="duration-editor">
            <div class="duration-field">
              <el-input-number
                v-model="form.duration.hours"
                :min="0"
                :max="720"
                :controls="false"
                placeholder="0"
              />
              <span class="duration-unit">时</span>
            </div>
            <div class="duration-field">
              <el-input-number
                v-model="form.duration.minutes"
                :min="0"
                :max="59"
                :controls="false"
                placeholder="0"
              />
              <span class="duration-unit">分</span>
            </div>
            <div class="duration-field">
              <el-input-number
                v-model="form.duration.seconds"
                :min="0"
                :max="59"
                :controls="false"
                placeholder="0"
              />
              <span class="duration-unit">秒</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="备注" prop="note">
          <el-input v-model="form.note" maxlength="255" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.timer-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.timer-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}

.timer-row.is-expired {
  background: var(--color-fill-light);
}

.timer-main {
  flex: 1;
  min-width: 0;
}

.timer-name {
  font-weight: 600;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timer-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 4px;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}

.timer-note {
  color: var(--color-text-secondary);
}

.timer-count {
  min-width: 132px;
  text-align: right;
  font-size: var(--font-lg);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: var(--color-brand-600, var(--color-primary));
}

.timer-row.is-expired .timer-count {
  font-size: var(--font-sm);
  font-weight: 500;
  color: var(--color-text-tertiary);
}

.duration-editor {
  display: flex;
  align-items: center;
  gap: 10px;
}

.duration-field {
  display: flex;
  align-items: center;
  gap: 4px;

  :deep(.el-input-number) {
    width: 74px;
  }
}

.duration-unit {
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}

.timers-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
</style>
