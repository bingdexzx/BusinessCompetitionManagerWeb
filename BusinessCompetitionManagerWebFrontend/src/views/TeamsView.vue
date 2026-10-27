<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import * as api from '@/api'
import type { Team, TeamJoinCode } from '@/api/types'
import { useCatalog } from '@/composables/useCatalog'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useCountUp, useFlash } from '@/composables/useMotion'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()
const auth = useAuthStore()

// 产业键 → 中文名（比赛包里的 manufacturer 这类 key 不直接展示）
const catalog = useCatalog(() => props.cid)
const industryLabel = catalog.industryLabel
const industryOptions = catalog.industryOptions

const teams = ref<Team[]>([])
const loading = ref(false)
const loaded = ref(false)
const loadError = ref('')
const initialLoading = computed(() => !loaded.value)

const summary = computed(() => {
  const total = teams.value.length
  const assigned = teams.value.filter((team) => team.companyName).length
  const members = teams.value.reduce((count, team) => count + (team.members?.length ?? 0), 0)
  return { total, assigned, unassigned: total - assigned, members }
})
const shownTeamCount = useCountUp(computed<number | null | undefined>(() => summary.value.total), {
  duration: 400,
})
const { flashing: summaryFlashing, flash: flashSummary } = useFlash(1200)

function initial(name: string): string {
  const trimmed = (name || '').trim()
  return trimmed ? Array.from(trimmed)[0]!.toUpperCase() : '?'
}

const showCreate = ref(false)
const creating = ref(false)
const createRef = ref<FormInstance>()
const createForm = ref({
  name: '',
  industryChoice: [] as string[],
  industryAdjustAccepted: [] as string[],
})
const createRules: FormRules = {
  name: [{ required: true, message: '请填写队伍名称', trigger: 'blur' }],
}

const showJoin = ref(false)
const joining = ref(false)
const joinCode = ref('')

const showAdjust = ref(false)
const adjusting = ref(false)
const adjustTarget = ref<Team | null>(null)
const adjustForm = ref({
  industryFinal: '',
  industryChoice: [] as string[],
  industryAdjustAccepted: [] as string[],
})

// 可调整产业：系统超管或本比赛超管
const canAdjust = computed(() => {
  if (auth.isSuperuser) return true
  return auth.memberships.some(
    (m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN',
  )
})

function isCaptain(team: Team): boolean {
  return team.captainId === auth.user?.id
}

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  const hadData = loaded.value
  try {
    teams.value = await api.getTeams(props.cid)
    if (hadData) flashSummary()
  } catch (err) {
    loadError.value = errorMessage(err, '操作失败')
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    loading.value = false
    loaded.value = true
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
    await api.createTeam(props.cid, {
      name: createForm.value.name.trim(),
      industryChoice: createForm.value.industryChoice,
      industryAdjustAccepted: createForm.value.industryAdjustAccepted,
    })
    ElMessage.success('队伍创建成功')
    showCreate.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    creating.value = false
  }
}

async function submitJoin(): Promise<void> {
  const code = joinCode.value.trim()
  if (!code) {
    ElMessage.warning('请输入组队码')
    return
  }
  joining.value = true
  try {
    const team = await api.joinTeam(props.cid, code)
    ElMessage.success(`已加入队伍「${team.name}」`)
    showJoin.value = false
    joinCode.value = ''
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    joining.value = false
  }
}

async function genJoinCode(team: Team): Promise<void> {
  let joinCodeInfo: TeamJoinCode
  try {
    joinCodeInfo = await api.createTeamJoinCode(props.cid, team.id)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
    return
  }
  try {
    await ElMessageBox.alert(
      `组队码：<strong>${joinCodeInfo.code}</strong><br/>` +
        `有效期至：${joinCodeInfo.expiresAt ? formatDateTime(joinCodeInfo.expiresAt) : '永久'}<br/>` +
        `可用次数：${joinCodeInfo.maxUses}，已用：${joinCodeInfo.usedCount}`,
      '组队码生成成功',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '关闭',
      },
    )
  } catch {
  }
}

function openAdjust(team: Team): void {
  adjustTarget.value = team
  adjustForm.value = {
    industryFinal: team.industryFinal,
    industryChoice: [...team.industryChoice],
    industryAdjustAccepted: [...team.industryAdjustAccepted],
  }
  showAdjust.value = true
}

async function submitAdjust(): Promise<void> {
  const target = adjustTarget.value
  if (!target) return
  const final = adjustForm.value.industryFinal.trim()
  if (!final) {
    ElMessage.warning('请填写最终产业')
    return
  }
  adjusting.value = true
  try {
    await api.adjustTeamIndustry(props.cid, target.id, {
      industryFinal: final,
      industryChoice: adjustForm.value.industryChoice,
      industryAdjustAccepted: adjustForm.value.industryAdjustAccepted,
    })
    ElMessage.success('产业已调整，公司已同步创建/更新')
    showAdjust.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    adjusting.value = false
  }
}

const showAssign = ref(false)
const assigning = ref(false)
const assignTarget = ref<Team | null>(null)
// 已导入产业（含中文名）：来自共享目录，随比赛包变更自动刷新
const industries = catalog.industries
const industriesLoading = catalog.loading
const assignForm = ref({
  industryKey: '',
  companyName: '',
})

// 默认产业：最终产业 → 首个志愿 → 首个已导入产业
async function openAssign(team: Team): Promise<void> {
  assignTarget.value = team
  assignForm.value = {
    industryKey:
      team.industryFinal || team.industryChoice?.[0] || industries.value[0]?.key || '',
    companyName: team.companyName || team.name,
  }
  showAssign.value = true
}

async function submitAssign(): Promise<void> {
  const target = assignTarget.value
  if (!target) return
  const industryKey = assignForm.value.industryKey.trim()
  const companyName = assignForm.value.companyName.trim()
  if (!industryKey) {
    ElMessage.warning('请选择产业')
    return
  }
  if (!companyName) {
    ElMessage.warning('请填写公司名称')
    return
  }
  assigning.value = true
  try {
    const team = await api.assignTeamCompany(props.cid, target.id, { industryKey, companyName })
    ElMessage.success(`公司已分配：${team.companyName || companyName}；队长已获得权限`)
    showAssign.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '分配失败'))
  } finally {
    assigning.value = false
  }
}

// 队伍/公司/用户变更后 400ms 去抖刷新
useResourceRefresh(['teams', 'companies', 'users'], load)

onMounted(() => void load())
</script>

<template>
  <div class="teams-page">
    <div class="page-toolbar">
      <h2 class="page-title">组队管理</h2>
      <div class="page-actions">
        <el-button @click="showJoin = true">
          <el-icon><Link /></el-icon>
          <span>加入队伍</span>
        </el-button>
        <el-button type="primary" @click="showCreate = true">
          <el-icon><Plus /></el-icon>
          <span>创建队伍</span>
        </el-button>
      </div>
    </div>

    <div v-if="initialLoading" class="team-grid" aria-busy="true">
      <div v-for="n in 3" :key="n" class="skeleton team-skeleton" />
    </div>

    <template v-else>
      <div v-if="loadError" class="notice notice--danger teams-error">
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="load">重试</el-button>
      </div>

      <div v-if="teams.length" class="metric-grid anim-fade-in-up">
        <div class="metric-card">
          <div class="metric-label">队伍总数</div>
          <div class="metric-value" :class="{ 'flash-updated': summaryFlashing }">
            {{ shownTeamCount }}<span class="metric-unit">支</span>
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">已分配公司</div>
          <div class="metric-value value-num">
            {{ summary.assigned }}<span class="metric-unit">支</span>
          </div>
        </div>
        <div class="metric-card" :class="{ 'metric-card--attention': summary.unassigned > 0 }">
          <div class="metric-label">待分配公司</div>
          <div class="metric-value value-num">
            {{ summary.unassigned }}<span class="metric-unit">支</span>
          </div>
        </div>
        <div class="metric-card">
          <div class="metric-label">队员总数</div>
          <div class="metric-value value-num">
            {{ summary.members }}<span class="metric-unit">人</span>
          </div>
        </div>
      </div>

      <div v-if="teams.length" v-loading="loading" class="team-list">
        <div class="team-grid anim-stagger">
          <article v-for="team in teams" :key="team.id" class="team-card hover-lift">
            <header class="team-card__head">
              <div class="team-card__title">
                <h3 class="team-name">{{ team.name }}</h3>
                <el-tag v-if="isCaptain(team)" size="small" type="warning" class="mini-tag">
                  我是队长
                </el-tag>
              </div>
              <span class="assign-badge" :class="team.companyName ? 'is-assigned' : 'is-pending'">
                {{ team.companyName ? '已分配公司' : '待分配公司' }}
              </span>
            </header>

            <div class="relation">
              <div class="relation-node">
                <span class="relation-label">队长</span>
                <span class="relation-value" :title="team.captainName">
                  {{ team.captainName || '—' }}
                </span>
              </div>
              <span class="relation-arrow" aria-hidden="true">→</span>
              <div class="relation-node">
                <span class="relation-label">公司</span>
                <span
                  class="relation-value"
                  :class="{ 'is-pending': !team.companyName }"
                  :title="team.companyName || '未分配公司'"
                >
                  {{ team.companyName || '未分配' }}
                </span>
              </div>
              <span class="relation-arrow" aria-hidden="true">→</span>
              <div class="relation-node">
                <span class="relation-label">最终产业</span>
                <span
                  class="relation-value"
                  :class="{ 'is-pending': !team.industryFinal }"
                  :title="industryLabel(team.industryFinal) || '产业未定'"
                >
                  {{ industryLabel(team.industryFinal) || '未定' }}
                </span>
              </div>
            </div>

            <div class="members">
              <span class="members-label">
                成员 {{ team.members?.length ?? 0 }} 人
              </span>
              <div class="member-list">
                <span
                  v-for="m in team.members ?? []"
                  :key="m.userId"
                  class="member-chip"
                  :class="{ 'is-captain': m.userId === team.captainId }"
                  :title="
                    m.userId === team.captainId
                      ? `${m.displayName || m.username}（队长）`
                      : m.displayName || m.username
                  "
                >
                  <el-avatar :size="20" class="member-avatar">
                    {{ initial(m.displayName || m.username) }}
                  </el-avatar>
                  <span class="member-name">{{ m.displayName || m.username }}</span>
                </span>
                <span v-if="!team.members?.length" class="muted">—</span>
              </div>
            </div>

            <div class="industry-row">
              <span class="industry-label">产业志愿</span>
              <div class="tag-list">
                <el-tag
                  v-for="c in team.industryChoice ?? []"
                  :key="c"
                  size="small"
                  class="mini-tag"
                >
                  {{ industryLabel(c) }}
                </el-tag>
                <span v-if="!team.industryChoice?.length" class="muted">—</span>
              </div>
            </div>

            <div class="industry-row">
              <span class="industry-label">接受调剂</span>
              <div class="tag-list">
                <el-tag
                  v-for="c in team.industryAdjustAccepted ?? []"
                  :key="c"
                  size="small"
                  type="info"
                  class="mini-tag"
                >
                  {{ industryLabel(c) }}
                </el-tag>
                <span v-if="!team.industryAdjustAccepted?.length" class="muted">—</span>
              </div>
            </div>

            <footer class="team-card__foot">
              <span class="created-at">创建于 {{ formatDateTime(team.createdAt) }}</span>
              <div class="team-card__actions">
                <el-button
                  v-if="isCaptain(team)"
                  size="small"
                  link
                  type="primary"
                  @click="genJoinCode(team)"
                >
                  生成组队码
                </el-button>
                <el-button
                  v-if="canAdjust"
                  size="small"
                  link
                  type="warning"
                  @click="openAdjust(team)"
                >
                  调整产业
                </el-button>
                <el-button
                  v-if="canAdjust"
                  size="small"
                  link
                  type="success"
                  @click="openAssign(team)"
                >
                  {{ team.companyName ? '修改公司' : '分配公司' }}
                </el-button>
              </div>
            </footer>
          </article>
        </div>
      </div>

      <div v-else-if="!loadError" class="panel empty-panel">
        <el-empty description="暂无队伍" />
      </div>
    </template>

    <el-dialog v-model="showCreate" title="创建队伍" width="520px" destroy-on-close>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="输入产业 key，回车添加"
        class="dialog-tip"
      />
      <el-form
        ref="createRef"
        :model="createForm"
        :rules="createRules"
        label-width="110px"
        @submit.prevent
      >
        <el-form-item label="队伍名称" prop="name">
          <el-input v-model="createForm.name" placeholder="例如：星辰队" maxlength="60" />
        </el-form-item>
        <el-form-item label="产业志愿">
          <el-select
            v-model="createForm.industryChoice"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="选择产业（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="opt in industryOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="接受调剂">
          <el-select
            v-model="createForm.industryAdjustAccepted"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="可接受的调剂产业（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="opt in industryOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showJoin" title="加入队伍" width="420px" destroy-on-close>
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="组队码">
          <el-input
            v-model="joinCode"
            placeholder="请输入队长提供的组队码"
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

    <el-dialog v-model="showAdjust" title="调整产业" width="520px" destroy-on-close>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="保存后同步创建/更新对应公司"
        class="dialog-tip"
      />
      <el-form :model="adjustForm" label-width="110px" @submit.prevent>
        <el-form-item label="最终产业">
          <el-select
            v-model="adjustForm.industryFinal"
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="选择该队伍最终确定的产业"
            style="width: 100%"
          >
            <el-option
              v-for="opt in industryOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="产业志愿">
          <el-select
            v-model="adjustForm.industryChoice"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="可一并修订产业志愿"
            style="width: 100%"
          >
            <el-option
              v-for="opt in industryOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="接受调剂">
          <el-select
            v-model="adjustForm.industryAdjustAccepted"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="可一并修订接受调剂范围"
            style="width: 100%"
          >
            <el-option
              v-for="opt in industryOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdjust = false">取消</el-button>
        <el-button type="primary" :loading="adjusting" @click="submitAdjust">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showAssign"
      :title="assignTarget?.companyName ? '修改公司' : '分配公司'"
      width="520px"
      destroy-on-close
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="分配后队长可操作本公司股票与合同，其他队员只读。"
        class="dialog-tip"
      />
      <el-form :model="assignForm" label-width="110px" @submit.prevent>
        <el-form-item label="产业" required>
          <el-select
            v-model="assignForm.industryKey"
            filterable
            :loading="industriesLoading"
            placeholder="请选择本比赛已导入的产业"
            style="width: 100%"
          >
            <el-option
              v-for="opt in industries"
              :key="opt.key"
              :label="opt.name ? `${opt.name}（${opt.key}）` : opt.key"
              :value="opt.key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="公司名称" required>
          <el-input
            v-model="assignForm.companyName"
            placeholder="例如：星辰科技"
            maxlength="120"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAssign = false">取消</el-button>
        <el-button type="primary" :loading="assigning" @click="submitAssign">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.teams-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.page-toolbar .page-title {
  margin-bottom: 0;
}

.page-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 8px;
}

.team-name {
  font-weight: 700;
  color: var(--color-text-primary);
  font-size: var(--font-lg);
  line-height: 1.4;
  word-break: break-word;
}

.mini-tag {
  margin: 0;
}

.muted {
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}

.dialog-tip {
  margin-bottom: 16px;
}

.teams-error {
  align-items: center;
  justify-content: space-between;
}

.team-list {
  min-height: 120px;
}

.team-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(340px, 100%), 1fr));
  gap: 16px;
  align-items: start;
}

.team-skeleton {
  height: 208px;
}

.team-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 18px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  /* 动画结束后交还 transform，保留悬停轻抬 */
  animation-fill-mode: backwards;
}

.team-card__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.team-card__title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

/* 已分配=成功色，待分配=醒目不告警 */
.assign-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-xs);
  font-weight: 600;
  white-space: nowrap;
  border: 1px solid transparent;
  color: var(--color-text-primary);

  &::before {
    content: "";
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-text-tertiary);
  }

  &.is-assigned {
    background: var(--color-success-soft);

    &::before {
      background: var(--color-success);
    }
  }

  &.is-pending {
    background: var(--color-warning-soft);
    border-color: rgba(var(--color-warning-soft-rgb), 0.6);
    border-style: dashed;

    &::before {
      background: var(--color-warning);
    }
  }
}

.relation {
  display: flex;
  align-items: stretch;
  gap: 8px;
  padding: 10px 12px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
  flex-wrap: wrap;
}

.relation-node {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1 1 0;
}

.relation-label {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}

.relation-value {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  &.is-pending {
    color: var(--color-warning);
  }
}

.relation-arrow {
  align-self: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
  line-height: 1;
}

.members {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.members-label {
  flex-shrink: 0;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}

.member-list {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}

.member-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 2px 8px 2px 2px;
  background: var(--color-surface-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  font-size: var(--font-xs);
  color: var(--color-text-secondary);

  &.is-captain {
    background: var(--color-warning-soft);
    border-color: rgba(var(--color-warning-soft-rgb), 0.55);
    color: var(--color-text-primary);
  }
}

.member-avatar {
  flex-shrink: 0;
  background: rgba(var(--color-primary-rgb), 0.12);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;

  .member-chip.is-captain & {
    background: rgba(var(--color-warning-soft-rgb), 0.35);
    color: var(--color-text-primary);
  }
}

.member-name {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.industry-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--font-sm);
}

.industry-label {
  flex: 0 0 64px;
  font-size: var(--font-xs);
  line-height: 24px;
  color: var(--color-text-tertiary);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}

.team-card__foot {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px dashed var(--color-border);
}

.created-at {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
}

.team-card__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.team-card__actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

/* 待分配用琥珀描边提示，不改数字颜色 */
.metric-card--attention {
  border-color: rgba(var(--color-warning-soft-rgb), 0.55);

  &::before {
    background: var(--color-warning);
  }
}

.empty-panel {
  padding: 24px;
}

@media (max-width: 640px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
}
</style>
