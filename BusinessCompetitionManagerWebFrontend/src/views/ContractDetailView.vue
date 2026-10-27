<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  confirmContract,
  deleteContract,
  getContract,
  getContractEffects,
  getContractLedger,
  getTeams,
  requestContractModify,
  reviewBackfill,
  reviewContractModify,
  reviewContractOtherParty,
  submitContract,
  submitContractChanges,
} from '@/api'
import type { Contract, ContractCheck, ContractEffect, ContractLedger, ContractParty, TimelineNode } from '@/api/types'
import { formatDateTime, toDisplay } from '@/utils/format'
import { opLabel } from '@/utils/fieldOps'
import { useAuthStore } from '@/stores/auth'
import { useNotifications, useResourceRefresh } from '@/composables/useNotifications'
import { useCatalog } from '@/composables/useCatalog'
import { useCountUp, useFlash } from '@/composables/useMotion'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string; id: string }>()

// 字段键 / 合同类型 / 输入项 / 参与方角色 → 中文名（均来自比赛包插件定义）
const { fieldLabel, contractTypeLabel, inputLabel, partyRoleLabel } = useCatalog(() => props.cid)
const router = useRouter()
const auth = useAuthStore()

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const STATUS_META: Record<string, { label: string; type: TagType }> = {
  BACKFILL_REVIEW: { label: '补录待审核', type: 'warning' },
  DRAFT: { label: '草稿', type: 'info' },
  PENDING_PARTY: { label: '待确认', type: 'warning' },
  PENDING_EXEC: { label: '待执行', type: 'primary' },
  EXECUTED: { label: '已执行', type: 'primary' },
  POSTED: { label: '已落账', type: 'success' },
  MOD_APPLYING: { label: '修改申请中', type: 'warning' },
  MOD_EDITING: { label: '修改中', type: 'warning' },
  EXEC_FAILED: { label: '执行失败', type: 'danger' },
  CANCELLED: { label: '已取消', type: 'info' },
}

function statusMeta(status: string): { label: string; type: TagType } {
  return STATUS_META[status] ?? { label: status, type: 'info' }
}

const TIMELINE_META: Record<string, { label: string; type: TagType }> = {
  CREATED: { label: '创建', type: 'info' },
  CONFIRM: { label: '参与方确认', type: 'primary' },
  NUMBERED: { label: '统一编号', type: 'warning' },
  EXECUTED: { label: '执行', type: 'success' },
  POSTED: { label: '落账', type: 'success' },
  MOD_APPLY: { label: '申请修改', type: 'warning' },
  MOD_REVIEW: { label: '修改审核', type: 'warning' },
  MOD_OTHER_PARTY: { label: '其他方表态', type: 'warning' },
  FIELD: { label: '字段变更', type: 'info' },
  WAITING: { label: '等待确认', type: 'primary' },
}

function timelineMeta(type: string): { label: string; type: TagType } {
  return TIMELINE_META[type] ?? { label: type, type: 'info' }
}

const contract = ref<Contract | null>(null)
const effects = ref<ContractEffect[]>([])
const loading = ref(false)
const effectsLoading = ref(false)
const loaded = ref(false)
const loadError = ref('')
const initialLoading = computed(() => !loaded.value)
const { flashing: overviewFlashing, flash: flashOverview } = useFlash(1200)
const shownEffectCount = useCountUp(
  computed<number | null | undefined>(() => effects.value.length),
  { duration: 400 },
)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    contract.value = await getContract(props.cid, Number(props.id))
  } catch (e) {
    loadError.value = errorMessage(e, '操作失败')
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    loading.value = false
    loaded.value = true
  }
}

async function loadEffects(): Promise<void> {
  // 效果审计只给超级管理员：非超管不发起请求（后端同样会 403）
  if (!canViewAudit.value) {
    effects.value = []
    return
  }
  effectsLoading.value = true
  try {
    effects.value = await getContractEffects(props.cid, Number(props.id))
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    effectsLoading.value = false
  }
}

// 账本链：当时值=审计，重演值=按当前内容重算
const ledger = ref<ContractLedger | null>(null)

async function loadLedger(): Promise<void> {
  // 账本链只给超级管理员：非超管不发起请求（后端同样会 403）
  if (!canViewAudit.value) {
    ledger.value = null
    return
  }
  try {
    ledger.value = await getContractLedger(props.cid, Number(props.id))
  } catch {
    ledger.value = null // 账本链为增强展示，失败不阻塞页面
  }
}

// 检查记录：修改后按轮次回放，依据带重演值
const checks = computed<ContractCheck[]>(() => ledger.value?.checks ?? contract.value?.checks ?? [])

const inputEntries = computed<Array<[string, unknown]>>(() =>
  Object.entries(contract.value?.inputs ?? {}),
)

watch(contract, (_next, prev) => {
  if (prev) flashOverview()
})

function effectRowClass({ row }: { row: ContractEffect }): string {
  return row.isCurrent ? '' : 'effect-rolled-back' // 已回滚轮次置灰（审计历史）
}

// 本合同被他人确认/修改后刷新；1s 内多条信号合并为一次
let refreshTimer: ReturnType<typeof setTimeout> | null = null
useNotifications((message) => {
  const payload = message.payload || {}
  if (payload.contractId !== Number(props.id)) return
  if (refreshTimer) return // 去抖：1s 内多条信号合并为一次刷新
  refreshTimer = setTimeout(() => {
    refreshTimer = null
    void load()
    void loadEffects()
    void loadLedger()
  }, 1000)
})

// 合同/公司/财年写操作后 400ms 去抖重拉
useResourceRefresh(['contracts', 'companies', 'fiscal-years'], load)

const sortedParties = computed<ContractParty[]>(() =>
  [...(contract.value?.parties ?? [])].sort((a, b) => a.confirmOrder - b.confirmOrder),
)

const confirmedPartyCount = computed(
  () => sortedParties.value.filter((party) => party.confirmAt).length,
)

const pendingParty = computed<ContractParty | null>(() => {
  const c = contract.value
  if (!c || c.status !== 'PENDING_PARTY') return null
  return sortedParties.value[c.pendingPartyIndex] ?? null
})

interface DisplayNode {
  type: string
  at: string
  title: string
  actor: string
  detail: string
  waiting: boolean
}

const timelineNodes = computed<DisplayNode[]>(() => {
  const nodes: DisplayNode[] = (contract.value?.timeline ?? []).map((n: TimelineNode) => ({
    type: n.type,
    at: n.at,
    title: n.title,
    actor: n.actor,
    detail: n.detail ?? '',
    waiting: false,
  }))
  const waiting = pendingParty.value
  if (waiting) {
    nodes.push({
      type: 'WAITING',
      at: '',
      title: `等待 ${waiting.companyName || partyRoleLabel(contract.value?.contractTypeKey, waiting.role)} 确认`,
      actor: '—',
      detail: `按确认顺序第 ${waiting.confirmOrder} 位参与方尚未确认`,
      waiting: true,
    })
  }
  return nodes
})

// 权限仅前端预判，最终以后端校验为准
const isCompSuperAdmin = computed(() =>
  auth.memberships.some(
    (m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN',
  ),
)
const canReview = computed(() => auth.isSuperuser || isCompSuperAdmin.value)
// 主席团（管理员）：能看到审计信息，但只限**自己管理的公司**（范围由后端按所辖公司过滤）
const isCommitteeAdmin = computed(() =>
  auth.memberships.some(
    (m) => String(m.id) === props.cid && m.identity === 'ADMIN',
  ),
)
// 「效果与账本」「确认时间线」「资金账本链（重演）」：参赛代表一律不可见；
// 超管看全部；主席团看所辖公司那部分（后端同样按 audit_company_ids 过滤）
const canViewAudit = computed(() => canReview.value || isCommitteeAdmin.value)

// 可操作公司：参赛代表=本队公司，管理员=所辖公司；null=未知按放开
const myCompanyIds = ref<Set<number> | null>(null)

async function loadMyCompanies(): Promise<void> {
  try {
    const teams = await getTeams(props.cid)
    const uid = auth.user?.id
    const ids = new Set<number>()
    for (const team of teams) {
      if (team.companyId != null && team.members.some((mm) => mm.userId === uid)) {
        ids.add(team.companyId)
      }
    }
    myCompanyIds.value = ids
  } catch {
    myCompanyIds.value = null // 未知：按放开处理，由后端最终校验
  }
}

const canActForPending = computed(() => {
  const user = auth.user
  if (!user) return true
  if (auth.isSuperuser) return true
  const m = auth.memberships.find((x) => String(x.id) === props.cid)
  if (!m) return true
  if (m.identity === 'COMP_SUPER_ADMIN') return true
  const companyId = pendingParty.value?.companyId
  if (companyId == null) return true
  if (m.identity === 'ADMIN') return m.managedCompanies.includes(companyId)
  return myCompanyIds.value === null || myCompanyIds.value.has(companyId)
})

const actionLoading = ref(false)

async function runAction(action: () => Promise<unknown>, success: string): Promise<void> {
  actionLoading.value = true
  try {
    await action()
    ElMessage.success(success)
    await load()
    await loadEffects()
    await loadLedger()
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    actionLoading.value = false
  }
}

function doSubmit(): void {
  void runAction(() => submitContract(props.cid, Number(props.id)), '合同已提交')
}

function doConfirm(): void {
  void runAction(() => confirmContract(props.cid, Number(props.id)), '已确认，末方确认后自动编号并落账')
}

// 删除（回滚）先回滚已落账效果；不回滚删除仅限无落账效果
async function removeContract(rollback: boolean): Promise<void> {
  const tip = rollback
    ? '删除（回滚）会先回滚该合同已落账的字段效果再删除，确定继续？'
    : '「不回滚删除」仅允许删除无落账效果的合同（草稿/失败态），确定继续？'
  try {
    await ElMessageBox.confirm(tip, '删除合同', { type: 'warning' })
  } catch {
    return
  }
  actionLoading.value = true
  try {
    await deleteContract(props.cid, Number(props.id), rollback)
    ElMessage.success('合同已删除')
    void router.push(`/competitions/${props.cid}/contracts`)
  } catch (e) {
    ElMessage.error(errorMessage(e, '删除失败'))
  } finally {
    actionLoading.value = false
  }
}

const showModifyDialog = ref(false)
const modifyReason = ref('')

function openModifyDialog(): void {
  modifyReason.value = ''
  showModifyDialog.value = true
}

function submitModifyRequest(): void {
  if (!modifyReason.value.trim()) {
    ElMessage.error('请填写修改原因')
    return
  }
  showModifyDialog.value = false
  void runAction(
    () => requestContractModify(props.cid, Number(props.id), modifyReason.value.trim()),
    '修改申请已提交，等待超管审核',
  )
}

type ReviewMode = 'modify' | 'otherParty' | 'backfill'
const showReviewDialog = ref(false)
const reviewMode = ref<ReviewMode>('modify')
const reviewAction = ref<'approve' | 'reject'>('approve')
const reviewNote = ref('')

const REVIEW_TITLES: Record<ReviewMode, string> = {
  modify: '修改申请审核',
  otherParty: '其他方表态',
  backfill: '补录审核',
}

function openReview(mode: ReviewMode, action: 'approve' | 'reject'): void {
  reviewMode.value = mode
  reviewAction.value = action
  reviewNote.value = ''
  showReviewDialog.value = true
}

function submitReview(): void {
  const cid = props.cid
  const id = Number(props.id)
  const action = reviewAction.value
  const note = reviewNote.value.trim() || undefined
  showReviewDialog.value = false
  const label = action === 'approve' ? '已通过' : '已驳回'
  const apiCall =
    reviewMode.value === 'modify'
      ? () => reviewContractModify(cid, id, action, note)
      : reviewMode.value === 'otherParty'
        ? () => reviewContractOtherParty(cid, id, action, note)
        : () => reviewBackfill(cid, id, action, note)
  void runAction(apiCall, label)
}

interface EditField {
  key: string
  kind: 'number' | 'boolean' | 'json' | 'text'
}

const showChangesDialog = ref(false)
const editFields = ref<EditField[]>([])
const editNumbers = ref<Record<string, number | undefined>>({})
const editBools = ref<Record<string, boolean>>({})
const editJsons = ref<Record<string, string>>({})
const editTexts = ref<Record<string, string>>({})

function setNumber(key: string, v: unknown): void {
  editNumbers.value[key] = typeof v === 'number' && !Number.isNaN(v) ? v : undefined
}

function openChangesDialog(): void {
  const inputs = contract.value?.inputs ?? {}
  const fields: EditField[] = []
  const nums: Record<string, number | undefined> = {}
  const bools: Record<string, boolean> = {}
  const jsons: Record<string, string> = {}
  const texts: Record<string, string> = {}
  for (const [key, value] of Object.entries(inputs)) {
    if (typeof value === 'number') {
      fields.push({ key, kind: 'number' })
      nums[key] = value
    } else if (typeof value === 'boolean') {
      fields.push({ key, kind: 'boolean' })
      bools[key] = value
    } else if (value !== null && typeof value === 'object') {
      fields.push({ key, kind: 'json' })
      jsons[key] = JSON.stringify(value, null, 2)
    } else {
      fields.push({ key, kind: 'text' })
      texts[key] = value === null || value === undefined ? '' : String(value)
    }
  }
  editFields.value = fields
  editNumbers.value = nums
  editBools.value = bools
  editJsons.value = jsons
  editTexts.value = texts
  showChangesDialog.value = true
}

function submitChanges(): void {
  const inputs: Record<string, unknown> = {}
  for (const f of editFields.value) {
    if (f.kind === 'number') {
      if (editNumbers.value[f.key] !== undefined) inputs[f.key] = editNumbers.value[f.key]
    } else if (f.kind === 'boolean') {
      inputs[f.key] = editBools.value[f.key]
    } else if (f.kind === 'json') {
      const raw = (editJsons.value[f.key] ?? '').trim()
      try {
        inputs[f.key] = raw ? JSON.parse(raw) : null
      } catch {
        ElMessage.error(`字段「${f.key}」不是合法 JSON`)
        return
      }
    } else {
      inputs[f.key] = editTexts.value[f.key]
    }
  }
  showChangesDialog.value = false
  void runAction(
    () => submitContractChanges(props.cid, Number(props.id), { inputs }),
    '修改已提交：旧效果已回滚并重新执行落账',
  )
}

onMounted(() => {
  void load()
  void loadEffects()
  void loadLedger()
  void loadMyCompanies()
})

watch(
  () => props.id,
  () => {
    void load()
    void loadEffects()
    void loadLedger()
  },
)

function goBack(): void {
  void router.push(`/competitions/${props.cid}/contracts`)
}
</script>

<template>
  <div v-loading="loading && !initialLoading" class="contract-detail-page">
    <div v-if="initialLoading" class="detail-skeleton" aria-busy="true">
      <div class="skeleton skeleton-head" />
      <div class="skeleton skeleton-block" />
      <div class="skeleton skeleton-block skeleton-block--tall" />
    </div>

    <template v-else>
      <div class="detail-header anim-fade-in-up">
        <div class="detail-header__main">
          <el-button class="back-btn" text @click="goBack">← 返回合同列表</el-button>
          <h1 class="page-title">
            {{ contract?.name || `合同 #${props.id}` }}
          </h1>
          <div class="meta-row">
            <span class="meta-item">类型：<b>{{ contractTypeLabel(contract?.contractTypeKey) || '—' }}</b></span>
            <el-tag :type="statusMeta(contract?.status ?? '').type">
              {{ statusMeta(contract?.status ?? '').label }}
            </el-tag>
            <el-tag v-if="contract?.isBackfill" type="warning">补录</el-tag>
          </div>
        </div>
        <div class="detail-header__number">
          <div class="number-label">统一编号</div>
          <div v-if="contract?.unifiedNumber" class="number-value text-gradient value-num">
            {{ contract.unifiedNumber }}
          </div>
          <div v-else class="number-value number-value--empty">未编号</div>
        </div>
      </div>

      <div v-if="loadError" class="notice notice--danger detail-error">
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="load">重试</el-button>
      </div>

      <section class="panel overview-panel anim-fade-in-up">
        <h2 class="section-title">概览</h2>
        <div class="metric-grid">
          <div class="metric-card">
            <div class="metric-label">合同轮次</div>
            <div class="metric-value value-num">
              {{ contract?.roundNo ?? 0 }}<span class="metric-unit">轮</span>
            </div>
          </div>
          <div class="metric-card">
            <div class="metric-label">财年</div>
            <div class="metric-value value-num">{{ contract?.fiscalYear ?? '—' }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">参与方确认</div>
            <div class="metric-value value-num">
              {{ confirmedPartyCount }}<span class="metric-unit">/ {{ sortedParties.length }} 家</span>
            </div>
          </div>
          <div class="metric-card" :class="{ 'flash-updated': overviewFlashing }">
            <div class="metric-label">落账效果</div>
            <div class="metric-value value-num">
              {{ shownEffectCount }}<span class="metric-unit">条</span>
            </div>
          </div>
        </div>
      </section>

      <section class="panel party-panel anim-fade-in-up">
        <h2 class="section-title">参与方</h2>
        <div v-if="sortedParties.length" class="party-grid">
          <div
            v-for="p in sortedParties"
            :key="p.role"
            class="party-card"
            :class="{ 'party-card--pending': pendingParty && p.role === pendingParty.role }"
          >
            <div class="party-card__head">
              <b>{{ p.companyName || '—' }}</b>
              <el-tag size="small" effect="plain">
                {{ partyRoleLabel(contract?.contractTypeKey, p.role) }}
              </el-tag>
            </div>
            <div class="party-card__body">
              <template v-if="p.confirmAt">
                <el-tag type="success" size="small">已确认</el-tag>
                <span class="party-confirm-info">
                  {{ p.confirmedBy || '—' }} · {{ formatDateTime(p.confirmAt) }}
                </span>
              </template>
              <template v-else>
                <el-tag type="warning" size="small">
                  {{ pendingParty && p.role === pendingParty.role ? '等待中' : '未确认' }}
                </el-tag>
                <span v-if="pendingParty && p.role === pendingParty.role" class="party-confirm-info">
                  等待 {{ p.companyName || p.role }} 确认
                </span>
              </template>
            </div>
          </div>
        </div>
        <el-empty v-else :image-size="60" description="暂无参与方" />
      </section>

      <section class="panel inputs-panel anim-fade-in-up">
        <h2 class="section-title">输入项</h2>
        <div v-if="inputEntries.length" class="input-grid">
          <div v-for="[key, value] in inputEntries" :key="key" class="input-item">
            <span class="input-key">{{ inputLabel(contract?.contractTypeKey, key) }}</span>
            <span class="input-value value-num">{{ toDisplay(value) }}</span>
          </div>
        </div>
        <el-empty v-else :image-size="60" description="暂无输入项" />
      </section>

      <section v-if="canViewAudit" class="panel effects-panel anim-fade-in-up">
        <h2 class="section-title">效果与账本</h2>
        <h3 class="section-title section-title--sub">检查记录</h3>
        <el-table :data="checks" border stripe style="width: 100%">
          <template #empty>
            <el-empty description="暂无检查记录" />
          </template>
          <el-table-column label="轮次" width="150" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.roundStatus === 'ACTIVE'" type="success" size="small">
                第 {{ row.roundNo }} 轮·生效
              </el-tag>
              <el-tag v-else type="info" size="small">第 {{ row.roundNo }} 轮·历史</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="检查点" width="160">
            <template #default="{ row }">{{ row.checkpointLabel }}</template>
          </el-table-column>
          <el-table-column label="结果" width="100" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.passed" type="success" size="small">通过</el-tag>
              <el-tag v-else type="danger" size="small">未通过</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="检查内容（问题清单）" min-width="260">
            <template #default="{ row }">
              <span v-if="!row.problems || row.problems.length === 0" class="num-empty">无问题</span>
              <div v-else class="check-problems">
                <div v-for="(p, i) in row.problems" :key="i" class="check-problem">· {{ p }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="检查依据（当时 → 重演）" min-width="240">
            <template #default="{ row }">
              <div v-if="row.basis && Object.keys(row.basis).length" class="basis-list">
                <div v-for="(fields, role) in row.basis" :key="role" class="basis-row">
                  <span class="basis-role">
                    {{ partyRoleLabel(contract?.contractTypeKey, String(role)) }}：
                  </span>
                  <template v-for="(val, field) in fields" :key="field">
                    <span class="basis-item">
                      {{ fieldLabel(String(field)) }}
                      <b class="basis-replay">{{ toDisplay(row.replayBasis?.[role]?.[field] ?? val) }}</b>
                      <span
                        v-if="toDisplay(row.replayBasis?.[role]?.[field] ?? val) !== toDisplay(val)"
                        class="basis-audit"
                      >（当时 {{ toDisplay(val) }}）</span>
                    </span>
                  </template>
                </div>
              </div>
              <span v-else class="num-empty">—</span>
            </template>
          </el-table-column>
          <el-table-column label="检查人 / 时间" width="220">
            <template #default="{ row }">
              {{ row.checkedBy }} · {{ formatDateTime(row.checkedAt) }}
            </template>
          </el-table-column>
        </el-table>

        <h3 class="section-title section-title--sub">效果审计（落账）</h3>
        <el-table
          v-loading="effectsLoading"
          :data="effects"
          :row-class="effectRowClass"
          border
          stripe
          style="width: 100%"
        >
          <template #empty>
            <el-empty description="暂无落账效果" />
          </template>
          <el-table-column label="字段" min-width="140">
            <template #default="{ row }">{{ fieldLabel(row.fieldKey) }}</template>
          </el-table-column>
          <el-table-column prop="op" label="操作" width="90" align="center">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ opLabel(row.op) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="值" min-width="110">
            <template #default="{ row }">{{ toDisplay(row.value) }}</template>
          </el-table-column>
          <el-table-column label="变更（前 → 后）" min-width="220">
            <template #default="{ row }">
              <span class="effect-before">{{ toDisplay(row.before) }}</span>
              <span class="effect-arrow"> → </span>
              <span class="effect-after">{{ toDisplay(row.after) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="重演（当前链）" min-width="220">
            <template #default="{ row }">
              <template v-if="row.isCurrent && row.replayBefore !== undefined">
                <span
                  class="effect-replay"
                  :class="{ 'replay-drift': toDisplay(row.replayBefore) !== toDisplay(row.before) }"
                >
                  {{ toDisplay(row.replayBefore) }} → {{ toDisplay(row.replayAfter) }}
                </span>
                <div v-if="toDisplay(row.replayBefore) !== toDisplay(row.before)" class="replay-tip">
                  上游已修改
                </div>
              </template>
              <span v-else class="num-empty">—</span>
            </template>
          </el-table-column>
          <el-table-column label="轮次状态" width="150" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.isCurrent" type="success" size="small">
                第 {{ row.roundNo }} 轮·生效中
              </el-tag>
              <el-tag v-else type="info" size="small" class="rolled-back-tag">
                第 {{ row.roundNo }} 轮·已回滚
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
          </el-table-column>
        </el-table>

        <template v-if="canViewAudit">
          <h3 v-if="ledger?.chains?.length" class="section-title section-title--sub">
            资金账本链（重演）
          </h3>
          <div v-if="ledger?.chains?.length" class="effects-hint">
            以重演值为当前账目口径，当时值仅作审计留存。
          </div>
        </template>
        <div
          v-for="chain in canViewAudit ? (ledger?.chains ?? []) : []"
          :key="`${chain.companyId}-${chain.fieldKey}`"
          class="ledger-chain"
        >
          <div class="ledger-head">
            <span class="ledger-title">公司 #{{ chain.companyId }} · 字段 <b>{{ fieldLabel(chain.fieldKey) }}</b></span>
            <span class="ledger-range">
              初始 <b>{{ toDisplay(chain.initialValue) }}</b>
              <span class="effect-arrow"> ⇒ </span>
              当前（重演） <b class="effect-after">{{ toDisplay(chain.currentValue) }}</b>
            </span>
          </div>
          <el-table :data="chain.nodes" border size="small" style="width: 100%">
            <el-table-column label="合同" min-width="180">
              <template #default="{ row }">
                <span class="ledger-contract">{{ row.unifiedNumber || row.contractName }}</span>
              </template>
            </el-table-column>
            <el-table-column label="效果" width="120">
              <template #default="{ row }">{{ opLabel(row.op) }} {{ toDisplay(row.value) }}</template>
            </el-table-column>
            <el-table-column label="重演（当前账目）" min-width="170">
              <template #default="{ row }">
                <span class="effect-replay">{{ toDisplay(row.replayBefore) }} → {{ toDisplay(row.replayAfter) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="当时（审计）" min-width="170">
              <template #default="{ row }">
                <span class="basis-audit">{{ toDisplay(row.auditBefore) }} → {{ toDisplay(row.auditAfter) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </section>

      <section v-if="canViewAudit" class="panel timeline-panel anim-fade-in-up">
        <h2 class="section-title">确认时间线</h2>
        <el-timeline v-if="timelineNodes.length > 0" class="confirm-timeline">
          <el-timeline-item
            v-for="(node, idx) in timelineNodes"
            :key="idx"
            :type="timelineMeta(node.type).type"
            :hollow="node.waiting"
            :timestamp="node.at ? formatDateTime(node.at) : '进行中'"
            placement="top"
            :class="{ 'timeline-item--waiting': node.waiting }"
          >
            <div class="node-card" :class="{ 'node-card--waiting': node.waiting }">
              <div class="node-title">
                <el-tag size="small" :type="timelineMeta(node.type).type">
                  {{ timelineMeta(node.type).label }}
                </el-tag>
                <b>{{ node.title }}</b>
              </div>
              <div class="node-meta">
                <span>操作人：{{ node.actor }}</span>
                <span v-if="node.at">时间：{{ formatDateTime(node.at) }}</span>
              </div>
              <div v-if="node.detail" class="node-detail" :class="{ 'node-detail--confirm': node.type === 'CONFIRM' }">
                <template v-if="node.type === 'CONFIRM'">
                  <div class="confirm-line">
                    {{ node.actor }} 于 {{ formatDateTime(node.at) }} 确认
                  </div>
                  <div class="device-line">设备信息：{{ node.detail }}</div>
                </template>
                <template v-else>{{ node.detail }}</template>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无时间线记录" />
      </section>

      <!-- 常驻操作条：滚动时始终可达 -->
      <div class="sticky-actions detail-actions" role="group" aria-label="状态操作">
        <div class="action-row">
          <template v-if="contract?.status === 'DRAFT'">
            <el-button type="primary" :loading="actionLoading" @click="doSubmit">提交</el-button>
          </template>

          <template v-else-if="contract?.status === 'PENDING_PARTY'">
            <el-button
              type="primary"
              :loading="actionLoading"
              :disabled="!canActForPending"
              @click="doConfirm"
            >
              确认
            </el-button>
            <span class="action-hint">
              <template v-if="canActForPending">
                末方确认后自动编号并落账
              </template>
              <template v-else>
                当前不是待确认方「{{
                  pendingParty?.companyName ||
                  partyRoleLabel(contract?.contractTypeKey, pendingParty?.role)
                }}」
              </template>
            </span>
          </template>

          <template v-else-if="contract?.status === 'POSTED'">
            <el-button type="warning" :loading="actionLoading" @click="openModifyDialog">
              申请修改
            </el-button>
            <span class="action-hint">需超管审核</span>
          </template>

          <template v-else-if="contract?.status === 'MOD_APPLYING'">
            <template v-if="canReview">
              <el-button
                type="success"
                :loading="actionLoading"
                @click="openReview('modify', 'approve')"
              >
                通过
              </el-button>
              <el-button
                type="danger"
                :loading="actionLoading"
                @click="openReview('modify', 'reject')"
              >
                驳回
              </el-button>
            </template>
            <span v-else class="action-hint">待超管审核</span>
          </template>

          <template v-else-if="contract?.status === 'MOD_EDITING'">
            <el-button
              type="success"
              :loading="actionLoading"
              @click="openReview('otherParty', 'approve')"
            >
              其他方通过
            </el-button>
            <el-button
              type="danger"
              :loading="actionLoading"
              @click="openReview('otherParty', 'reject')"
            >
              其他方驳回
            </el-button>
            <el-button type="primary" :loading="actionLoading" @click="openChangesDialog">
              提交修改
            </el-button>
            <span class="action-hint">提交后回滚旧效果并重新落账</span>
          </template>

          <template v-else-if="contract?.status === 'BACKFILL_REVIEW'">
            <template v-if="canReview">
              <el-button
                type="success"
                :loading="actionLoading"
                @click="openReview('backfill', 'approve')"
              >
                补录通过
              </el-button>
              <el-button
                type="danger"
                :loading="actionLoading"
                @click="openReview('backfill', 'reject')"
              >
                补录驳回
              </el-button>
            </template>
            <span v-else class="action-hint">待超管审核</span>
          </template>

          <span v-else class="action-hint">暂无可用操作</span>
        </div>

        <div v-if="canReview" class="action-row delete-row">
          <el-button type="danger" plain :loading="actionLoading" @click="removeContract(true)">
            删除（回滚）
          </el-button>
          <el-button type="danger" plain :loading="actionLoading" @click="removeContract(false)">
            不回滚删除
          </el-button>
          <span class="action-hint">「删除（回滚）」先回滚已落账效果再删；「不回滚删除」仅限无落账效果的合同</span>
        </div>
      </div>
    </template>

    <el-dialog v-model="showModifyDialog" title="申请修改" width="520px" append-to-body>
      <el-form label-position="top">
        <el-form-item label="修改原因" required>
          <el-input
            v-model="modifyReason"
            type="textarea"
            :rows="4"
            placeholder="请说明申请修改的原因"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showModifyDialog = false">取消</el-button>
        <el-button type="primary" :loading="actionLoading" @click="submitModifyRequest">
          提交申请
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showReviewDialog"
      :title="`${REVIEW_TITLES[reviewMode]}（${reviewAction === 'approve' ? '通过' : '驳回'}）`"
      width="520px"
      append-to-body
    >
      <el-form label-position="top">
        <el-form-item label="审核意见">
          <el-input
            v-model="reviewNote"
            type="textarea"
            :rows="4"
            placeholder="可填写审核意见（可留空）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showReviewDialog = false">取消</el-button>
        <el-button
          :type="reviewAction === 'approve' ? 'success' : 'danger'"
          :loading="actionLoading"
          @click="submitReview"
        >
          {{ reviewAction === 'approve' ? '通过' : '驳回' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showChangesDialog" title="提交修改" width="600px" append-to-body>
      <el-form label-position="top">
        <el-form-item
          v-for="f in editFields"
          :key="f.key"
          :label="f.key"
        >
          <el-input-number
            v-if="f.kind === 'number'"
            :model-value="editNumbers[f.key]"
            :controls="false"
            style="width: 100%"
            @update:model-value="(v: unknown) => setNumber(f.key, v)"
          />
          <el-switch v-else-if="f.kind === 'boolean'" v-model="editBools[f.key]" />
          <el-input
            v-else-if="f.kind === 'json'"
            v-model="editJsons[f.key]"
            type="textarea"
            :rows="4"
            placeholder="JSON 值"
          />
          <el-input v-else v-model="editTexts[f.key]" />
        </el-form-item>
        <el-empty
          v-if="editFields.length === 0"
          :image-size="60"
          description="该合同没有可修改的数据字段"
        />
      </el-form>
      <template #footer>
        <el-button @click="showChangesDialog = false">取消</el-button>
        <el-button type="primary" :loading="actionLoading" @click="submitChanges">
          提交修改
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.contract-detail-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}
.detail-header__main {
  flex: 1 1 380px;
  min-width: 0;
}
.back-btn {
  margin-bottom: 4px;
}
.detail-header .page-title {
  margin-bottom: 10px;
}
.meta-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}
.meta-item b {
  color: var(--color-text-primary);
}
.detail-header__number {
  background: var(--surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 14px 22px;
  box-shadow: var(--shadow-sm);
  text-align: center;
}
.number-label {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
  letter-spacing: 0.08em;
  margin-bottom: 2px;
}
.number-value {
  font-size: var(--font-xl);
  font-weight: 700;
  letter-spacing: 0.02em;
}
.number-value--empty {
  color: var(--color-text-tertiary);
}

.panel {
  padding: 20px 22px;
}

// 分区入场只做一次，不循环
.overview-panel {
  --anim-delay: 40ms;
}
.party-panel {
  --anim-delay: 80ms;
}
.inputs-panel {
  --anim-delay: 120ms;
}
.effects-panel {
  --anim-delay: 160ms;
}
.timeline-panel {
  --anim-delay: 200ms;
}

.section-title--sub {
  font-size: var(--font-base);
  margin-top: 18px;
  margin-bottom: 10px;
  color: var(--color-text-secondary);
}

h2.section-title + .section-title--sub {
  margin-top: 0;
}

.overview-panel .metric-grid {
  margin-top: 2px;
}

.input-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px 14px;
}
.input-item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
}
.input-key {
  font-size: var(--font-sm);
  color: var(--color-text-secondary);
  word-break: break-all;
}
.input-value {
  font-size: var(--font-base);
  font-weight: 600;
  color: var(--color-text-primary);
  text-align: right;
  word-break: break-word;
}

.action-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.action-hint {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
  order: -1;
  margin-right: auto;
}
.detail-actions {
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  gap: 6px;
  padding: 10px 16px;
  margin-top: 0;
  /* 抵消内容区底部内距，让常驻条贴合视口底 */
  bottom: calc(var(--content-padding) * -1);
  border-radius: var(--radius-md) var(--radius-md) 0 0;
}
.detail-actions .action-row {
  justify-content: flex-end;
}
.detail-actions .delete-row {
  padding-top: 6px;
  border-top: 1px dashed var(--color-border);
}

.detail-skeleton {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.skeleton-head {
  height: 96px;
}
.skeleton-block {
  height: 168px;
}
.skeleton-block--tall {
  height: 280px;
}
.detail-error {
  align-items: center;
  justify-content: space-between;
}

.node-card {
  background: var(--surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
}
.node-card--waiting {
  border-color: rgba(var(--color-warning-soft-rgb), 0.5);
  background: var(--color-warning-soft);
}
.node-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.node-meta {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}
.node-detail {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--color-border);
  color: var(--el-text-color-regular);
  font-size: var(--font-sm);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.node-detail--confirm {
  background: var(--color-info-soft);
  border: none;
  border-radius: var(--radius-xs);
  padding: 8px 10px;
  margin-top: 8px;
}
.confirm-line {
  font-weight: 600;
  color: var(--color-text-primary);
}
.device-line {
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
}

.party-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.party-card {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  background: var(--surface-raised);
}
.party-card--pending {
  border-color: var(--color-warning);
  background: var(--color-warning-soft);
}
.party-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.party-card__body {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.party-confirm-info {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}

.effect-before {
  color: var(--color-text-tertiary);
}
.effect-arrow {
  color: var(--color-text-tertiary);
}
.effect-after {
  color: var(--color-primary);
  font-weight: 600;
}
.effects-hint {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
  margin-bottom: 10px;
  line-height: 1.7;
}
// 已回滚轮次置灰（审计历史）
:deep(tr.effect-rolled-back) {
  opacity: 0.55;
}
:deep(tr.effect-rolled-back .effect-after) {
  color: var(--color-text-tertiary);
  font-weight: 400;
  text-decoration: line-through;
}
.rolled-back-tag {
  text-decoration: none;
}

.check-problems {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.check-problem {
  color: var(--color-danger, #ef4444);
  font-size: var(--font-sm);
}
.basis-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--font-sm);
}
.basis-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.basis-role {
  color: var(--color-text-tertiary);
}
.basis-item {
  color: var(--color-text-secondary);
}
.basis-replay {
  color: var(--color-primary);
  font-weight: 600;
}
.basis-audit {
  color: var(--color-text-tertiary);
  text-decoration: line-through;
}

.effect-replay {
  color: var(--color-accent, #8b5cf6);
  font-weight: 600;
}
.replay-drift {
  color: var(--color-warning, #f59e0b);
}
.replay-tip {
  color: var(--color-warning, #f59e0b);
  font-size: 12px;
  margin-top: 2px;
}
.ledger-chain {
  margin-bottom: 18px;
}
.ledger-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.ledger-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.ledger-range {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}
.ledger-contract {
  font-weight: 500;
}

/* 手机概览两列，减少首屏空白 */
@media (max-width: 640px) {
  .overview-panel .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
}
</style>
