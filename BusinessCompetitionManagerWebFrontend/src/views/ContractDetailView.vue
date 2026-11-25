<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  confirmContract,
  deleteContract,
  getCompanies,
  getContract,
  getContractEffects,
  getContractLedger,
  getTeams,
  requestContractModify,
  reviewBackfill,
  reviewContractModify,
  rejectContract,
  submitContract,
  terminateContract,
  submitContractChanges,
  updateContractDraft,
} from '@/api'
import type { Company, Contract, ContractCheck, ContractEffect, ContractLedger, ContractParty, TimelineNode } from '@/api/types'
import { formatDateTime, toDisplay } from '@/utils/format'
import { opLabel } from '@/utils/fieldOps'
import { useAuthStore } from '@/stores/auth'
import { useNotifications, useResourceRefresh } from '@/composables/useNotifications'
import { listTableOf, useListOptions } from '@/composables/useListOptions'
import { useCatalog } from '@/composables/useCatalog'
import { errorMessage } from '@/utils/errors'
const props = defineProps<{ cid: string; id: string }>()
// 字段键 / 合同类型 / 输入项 / 参与方角色 → 中文名（均来自比赛包插件定义）
const { fieldLabel, contractTypeLabel, inputLabel, partyRoleLabel, contractTypes } = useCatalog(() => props.cid)
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
/** 效果与账本只展示当前生效链：已回滚轮次不进表格 */
const currentEffects = computed(() => effects.value.filter((e) => e.isCurrent))
const loading = ref(false)
const effectsLoading = ref(false)
const loaded = ref(false)
const loadError = ref('')
const initialLoading = computed(() => !loaded.value)
// 标签页：审计类标签仅对超级管理员可见（参赛代表只看合同内容）
type TabKey = 'basic' | 'timeline' | 'checks' | 'effects'
const activeTab = ref<TabKey>('basic')
async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [contractData, companyRows] = await Promise.all([
      getContract(props.cid, Number(props.id)),
      getCompanies(props.cid).catch(() => [] as Company[]),
    ])
    contract.value = contractData
    companies.value = companyRows
  } catch (e) {
    loadError.value = errorMessage(e, '加载失败')
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    loading.value = false
    loaded.value = true
  }
}
async function loadEffects(): Promise<void> {
  // 效果审计只给超级管理员：非超级管理员不发起请求（后端同样会 403）
  if (!canViewAudit.value) {
    effects.value = []
    return
  }
  effectsLoading.value = true
  try {
    effects.value = await getContractEffects(props.cid, Number(props.id))
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    effectsLoading.value = false
  }
}
// 账本链：当时值=审计，重演值=按当前内容重算
const ledger = ref<ContractLedger | null>(null)
async function loadLedger(): Promise<void> {
  // 账本链只给超级管理员：非超级管理员不发起请求（后端同样会 403）
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
/** 效果对象：始终显示发起/归属的公司名（区域字段效果的公司为发起该效果的公司） */
function effectTargetName(row: ContractEffect): string {
  const party = (contract.value?.parties ?? []).find((p) => p.companyId === row.companyId)
  return party?.companyName || (row.companyId ? `#${row.companyId}` : '—')
}
const companies = ref<Company[]>([])
const companyNameById = computed(() => {
  const map = new Map<number, string>()
  for (const c of companies.value) map.set(c.id, c.name)
  for (const p of contract.value?.parties ?? []) {
    if (p.companyId != null && !map.has(p.companyId)) {
      map.set(p.companyId, p.companyName || `#${p.companyId}`)
    }
  }
  return map
})
function inputSchemaOf(key: string) {
  return (
    contractTypes.value.find((t) => t.key === contract.value?.contractTypeKey)?.inputSchema ?? []
  ).find((s) => s.key === key)
}
/** LIST 类型输入（如原料清单）在详情页用表格展示 */
function isListKey(key: string): boolean {
  return String(inputSchemaOf(key)?.type ?? '').toUpperCase().startsWith('LIST')
}
function listRows(key: string, value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return []
  return value.map((row) => (row && typeof row === 'object' ? (row as Record<string, unknown>) : { item: String(row) }))
}
function listItemLabel(key: string): string {
  return inputSchemaOf(key)?.itemLabel || '原料'
}
function listSubFields(key: string): Array<{ key: string; label?: string }> {
  const fields = inputSchemaOf(key)?.fields
  return fields && fields.length ? fields : [{ key: 'quantity', label: '数量' }]
}
/** 清单合计（数量 × 单价），没有单价列时不显示 */
function listTotal(key: string, value: unknown): number | null {
  const fields = listSubFields(key).map((f) => f.key)
  if (!fields.includes('quantity') || !fields.includes('unitPrice')) return null
  return listRows(key, value).reduce((sum, row) => {
    const quantity = Number(row.quantity)
    const price = Number(row.unitPrice)
    if (!Number.isFinite(quantity) || !Number.isFinite(price)) return sum
    return sum + quantity * price
  }, 0)
}
/** 输入项展示：REF:companies 类公司引用显示公司名，其余按原值展示 */
function formatInputValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value
      .map((row) => {
        if (row && typeof row === 'object') {
          const record = row as Record<string, unknown>
          const item = String(record.item ?? '')
          const extras = Object.entries(record)
            .filter(([key, cell]) => key !== 'item' && cell !== undefined && cell !== null)
            .map(([, cell]) => String(cell))
          return extras.length ? `${item}（${extras.join('，')}）` : item
        }
        return String(row)
      })
      .filter(Boolean)
      .join('；')
  }
  return toDisplay(value)
}
function inputDisplay(key: string, value: unknown): string {
  const schema = (
    contractTypes.value.find((t) => t.key === contract.value?.contractTypeKey)?.inputSchema ?? []
  ).find((s) => s.key === key)
  const type = String(schema?.type ?? '').toUpperCase()
  if (type.startsWith('LIST')) return formatInputValue(value)
  if (type.startsWith('REF') && type.includes('COMPAN')) {
    const id = Number(value)
    const name = Number.isFinite(id) ? companyNameById.value.get(id) : undefined
    if (name) return name
  }
  return formatInputValue(value)
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
const confirmedPercent = computed(() => {
  const total = sortedParties.value.length
  return total ? Math.round((confirmedPartyCount.value / total) * 100) : 0
})
const pendingParty = computed<ContractParty | null>(() => {
  const c = contract.value
  if (!c || c.status !== 'PENDING_PARTY') return null
  return sortedParties.value[c.pendingPartyIndex] ?? null
})
// 主流程进度：草稿 → 参与方确认 → 待执行 → 已执行 → 已落账（修改环/失败/取消用提示说明）
type TrackStep = { key: string; label: string; state: 'done' | 'active' | 'todo' }
const TRACK_LABELS = ['草稿', '参与方确认', '待执行', '已执行', '已落账']
const TRACK_INDEX: Record<string, number> = {
  BACKFILL_REVIEW: 0,
  DRAFT: 0,
  PENDING_PARTY: 1,
  PENDING_EXEC: 2,
  EXECUTED: 3,
  POSTED: 4,
  MOD_APPLYING: 4,
  MOD_EDITING: 4,
  EXEC_FAILED: 3,
  CANCELLED: 4,
}
const statusTrack = computed<TrackStep[]>(() => {
  const status = contract.value?.status ?? ''
  // 已取消：主流程全部置灰，用 trackNote 说明，避免误读成已落账
  if (status === 'CANCELLED') {
    return TRACK_LABELS.map((label) => ({ key: label, label, state: 'todo' as const }))
  }
  const index = TRACK_INDEX[status] ?? 0
  return TRACK_LABELS.map((label, i) => ({
    key: label,
    label,
    state: i < index ? 'done' : i === index ? 'active' : 'todo',
  }))
})
const trackNote = computed(() => {
  const c = contract.value
  if (!c) return ''
  if (c.status === 'MOD_APPLYING') return '修改申请中：等待超级管理员审核'
  if (c.status === 'MOD_EDITING') return '修改中：超级管理员已批准，申请方修改内容后直接提交'
  if (c.status === 'BACKFILL_REVIEW') return '补录合同：等待超级管理员审核后进入确认链'
  if (c.status === 'EXEC_FAILED') return '执行失败：合同未落半账，请核对原因后再处理'
  if (c.status === 'CANCELLED') return '合同已取消'
  if (c.status === 'PENDING_PARTY' && pendingParty.value) {
    return `等待「${
      pendingParty.value.companyName ||
      partyRoleLabel(c.contractTypeKey, pendingParty.value.role)
    }」确认`
  }
  return ''
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
const canReview = computed(() => auth.isSuperuser)
/** 合同写操作：仅系统超级管理员 / 本比赛主席团；参赛选手只读 */
const canOperateContract = computed(
  () =>
    auth.isSuperuser ||
    auth.memberships.some((m) => String(m.id) === props.cid && m.identity === 'ADMIN'),
)
// 管理员（主席团）：审计信息只到所辖公司（后端按 audit_company_ids 过滤）
const isCommitteeAdmin = computed(() =>
  auth.memberships.some(
    (m) => String(m.id) === props.cid && m.identity === 'ADMIN',
  ),
)
// 「效果与账本」「确认时间线」「检查记录」：参赛代表一律不可见；
// 系统超级管理员看全部；管理员看所辖公司那部分
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
  const companyId = pendingParty.value?.companyId
  if (companyId == null) return true
  if (m.identity === 'ADMIN') return (m.managedCompanies ?? []).includes(companyId)
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
async function doReject(): Promise<void> {
  const result = await ElMessageBox.prompt('请填写拒绝原因（可留空）', '拒绝确认', {
    confirmButtonText: '拒绝并退回草稿',
    cancelButtonText: '取消',
    inputType: 'textarea',
    inputPlaceholder: '例如：价格与约定不一致',
  }).catch(() => null)
  if (!result) return
  await runAction(
    () => rejectContract(props.cid, Number(props.id), String(result.value ?? '')),
    '已退回草稿，修改后可重新提交',
  )
}
/** 弹窗模式：提交修改 / 编辑草稿（草稿编辑走 PATCH 草稿接口） */
const changesMode = ref<'changes' | 'draft'>('changes')
function openDraftEdit(): void {
  openChangesDialog('draft')
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
    await ElMessageBox.confirm(tip, '删除合同', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
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
    ElMessage.warning('请填写修改原因')
    return
  }
  showModifyDialog.value = false
  void runAction(
    () => requestContractModify(props.cid, Number(props.id), modifyReason.value.trim()),
    '修改申请已提交，等待超级管理员审核',
  )
}
type ReviewMode = 'modify' | 'backfill'
const showReviewDialog = ref(false)
const reviewMode = ref<ReviewMode>('modify')
const reviewAction = ref<'approve' | 'reject'>('approve')
const reviewNote = ref('')
const REVIEW_TITLES: Record<ReviewMode, string> = {
  modify: '修改申请审核',
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
      : () => reviewBackfill(cid, id, action, note)
  void runAction(apiCall, label)
}
interface EditField {
  key: string
  label?: string
  kind: 'number' | 'boolean' | 'json' | 'text' | 'list'
  /** 原始输入类型（LIST:parts / REF:companies 之类，用来选下拉选项表） */
  type?: string
  /** 选填清单：留空允许 */
  optional?: boolean
  itemLabel?: string
  fields?: Array<{ key: string; label: string; type: string; min?: number }>
}
interface ListRow {
  item: string
  [key: string]: unknown
}
function listRowNumber(row: ListRow, key: string): number | undefined {
  const value = row[key]
  return typeof value === 'number' ? value : undefined
}
function setListRowNumber(row: ListRow, key: string, value: unknown): void {
  row[key] = typeof value === 'number' ? value : undefined
}
const showChangesDialog = ref(false)
const editFields = ref<EditField[]>([])
const editNumbers = ref<Record<string, number | undefined>>({})
const editBools = ref<Record<string, boolean>>({})
const editJsons = ref<Record<string, string>>({})
const editTexts = ref<Record<string, string>>({})
const editLists = ref<Record<string, ListRow[]>>({})
// 清单行选项按引用表取（原料/零件/产品/地图节点）
const { optionsFor, ensure: ensureListOptions } = useListOptions(Number(props.cid))
const listTable = listTableOf

/** REF:<表> 输入项 → 下拉选条目 */
function isRefType(type: string | undefined): boolean {
  return String(type ?? '').toUpperCase().startsWith('REF')
}
function addEditListRow(key: string): void {
  const rows = editLists.value[key] ?? []
  rows.push({ item: '' })
  editLists.value = { ...editLists.value, [key]: rows }
}
function removeEditListRow(key: string, index: number): void {
  const rows = editLists.value[key] ?? []
  rows.splice(index, 1)
  editLists.value = { ...editLists.value, [key]: rows }
}
function setNumber(key: string, v: unknown): void {
  editNumbers.value[key] = typeof v === 'number' && !Number.isNaN(v) ? v : undefined
}
/** 输入项类型 → 编辑控件种类 */
function kindOfInputType(type: string): EditField['kind'] {
  const t = String(type || '').toUpperCase()
  if (t.includes('NUMBER') || t === 'INT' || t === 'FLOAT') return 'number'
  if (t.includes('BOOL')) return 'boolean'
  if (t.startsWith('LIST')) return 'list'
  if (t.includes('JSON') || t.includes('OBJECT') || t.includes('ARRAY')) return 'json'
  return 'text'
}
function openChangesDialog(mode: 'changes' | 'draft' = 'changes'): void {
  changesMode.value = mode
  const inputs = contract.value?.inputs ?? {}
  const schema =
    contractTypes.value.find((t) => t.key === contract.value?.contractTypeKey)?.inputSchema ?? []
  const fields: EditField[] = []
  const nums: Record<string, number | undefined> = {}
  const bools: Record<string, boolean> = {}
  const jsons: Record<string, string> = {}
  const texts: Record<string, string> = {}
  const lists: Record<string, ListRow[]> = {}
  // 先按合同类型的定义铺满所有输入项（历史合同缺项也能在这里补齐）
  const seen = new Set<string>()
  for (const s of schema) {
    seen.add(s.key)
    const kind = kindOfInputType(s.type)
    const value = inputs[s.key]
    if (kind === 'number') {
      fields.push({ key: s.key, label: s.label, kind, type: s.type })
      nums[s.key] = typeof value === 'number' ? value : undefined
    } else if (kind === 'boolean') {
      fields.push({ key: s.key, label: s.label, kind })
      bools[s.key] = value === true
    } else if (kind === 'list') {
      fields.push({
        key: s.key,
        label: s.label,
        kind,
        type: s.type,
        optional: s.optional,
        itemLabel: s.itemLabel,
        fields: s.fields,
      })
      const rows = Array.isArray(value) ? value : []
      lists[s.key] = rows.map((row: Record<string, unknown>) => {
        const record: ListRow = { item: String(row?.item ?? '') }
        for (const sub of s.fields ?? []) {
          const cell = row?.[sub.key]
          record[sub.key] = Number.isFinite(Number(cell)) ? Number(cell) : undefined
        }
        return record
      })
      if (!(lists[s.key] ?? []).length && !s.optional) {
        lists[s.key] = [{ item: '' }]
      }
    } else if (kind === 'json') {
      fields.push({ key: s.key, label: s.label, kind })
      jsons[s.key] = value === null || value === undefined ? '' : JSON.stringify(value, null, 2)
    } else {
      fields.push({ key: s.key, label: s.label, kind, type: s.type })
      texts[s.key] = value === null || value === undefined ? '' : String(value)
    }
  }
  for (const [key, value] of Object.entries(inputs)) {
    if (seen.has(key)) continue
    const label = inputLabel(contract.value?.contractTypeKey, key)
    if (typeof value === 'number') {
      fields.push({ key, label, kind: 'number' })
      nums[key] = value
    } else if (typeof value === 'boolean') {
      fields.push({ key, label, kind: 'boolean' })
      bools[key] = value
    } else if (value !== null && typeof value === 'object') {
      fields.push({ key, label, kind: 'json' })
      jsons[key] = JSON.stringify(value, null, 2)
    } else {
      fields.push({ key, label, kind: 'text' })
      texts[key] = value === null || value === undefined ? '' : String(value)
    }
  }
  editFields.value = fields
  editNumbers.value = nums
  editBools.value = bools
  editJsons.value = jsons
  editTexts.value = texts
  editLists.value = lists
  for (const f of fields) {
    if (f.kind === 'list' && f.type) void ensureListOptions(listTable(f.type))
    else if (f.kind === 'text' && isRefType(f.type)) {
      const refTable = (String(f.type).split(':')[1] ?? '').trim().toLowerCase()
      if (refTable) void ensureListOptions(refTable)
    }
  }
  showChangesDialog.value = true
}
function submitChanges(): void {
  // 2026-11 决策：合同输入项一律必填，缺一项都不让提交
  const inputs: Record<string, unknown> = {}
  for (const f of editFields.value) {
    const label = f.label ?? f.key
    if (f.kind === 'number') {
      const value = editNumbers.value[f.key]
      if (value === undefined || value === null) {
        ElMessage.warning(`请输入「${label}」`)
        return
      }
      inputs[f.key] = value
    } else if (f.kind === 'boolean') {
      inputs[f.key] = editBools.value[f.key] === true
    } else if (f.kind === 'list') {
      const rows = editLists.value[f.key] ?? []
      if (!rows.length) {
        if (f.optional) continue
        ElMessage.warning(`请添加「${label}」`)
        return
      }
      for (const row of rows) {
        if (!row.item) {
          ElMessage.warning(`「${label}」有未选择${f.itemLabel || '明细'}的行`)
          return
        }
        for (const sub of f.fields ?? []) {
          if (listRowNumber(row, sub.key) === undefined) {
            ElMessage.warning(`「${label}」有未填写${sub.label || sub.key}的行`)
            return
          }
        }
      }
      inputs[f.key] = rows.map((row) => {
        const record: Record<string, unknown> = { item: row.item }
        for (const sub of f.fields ?? []) record[sub.key] = row[sub.key]
        return record
      })
      continue
    } else if (f.kind === 'json') {
      const raw = (editJsons.value[f.key] ?? '').trim()
      if (!raw) {
        ElMessage.warning(`请输入「${label}」`)
        return
      }
      try {
        inputs[f.key] = JSON.parse(raw)
      } catch {
        ElMessage.warning(`字段「${label}」不是合法 JSON`)
        return
      }
    } else {
      const value = (editTexts.value[f.key] ?? '').trim()
      if (!value) {
        ElMessage.warning(`请输入「${label}」`)
        return
      }
      inputs[f.key] = value
    }
  }
  showChangesDialog.value = false
  if (changesMode.value === 'draft') {
    void runAction(
      () => updateContractDraft(props.cid, Number(props.id), { inputs }),
      '草稿已保存，可重新提交',
    )
    return
  }
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
    activeTab.value = 'basic'
    void load()
    void loadEffects()
    void loadLedger()
  },
)
function goBack(): void {
  void router.push(`/competitions/${props.cid}/contracts`)
}
function onMoreCommand(command: unknown): void {
  if (command === 'terminate') {
    void terminate()
    return
  }
  void removeContract(command === 'rollback')
}
async function terminate(): Promise<void> {
  const result = await ElMessageBox.prompt(
    '终止后合同作废，已落账的字段效果会回滚。请填写终止原因（可留空）',
    '终止合同',
    {
      confirmButtonText: '终止合同',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputPlaceholder: '例如：比赛规则调整，该合同不再执行',
    },
  ).catch(() => null)
  if (!result) return
  await runAction(
    () => terminateContract(props.cid, Number(props.id), String(result.value ?? '')),
    '合同已终止',
  )
}
</script>
<template>
  <div v-loading="loading && !initialLoading" class="contract-detail-page page">
    <div v-if="initialLoading" class="detail-skeleton" aria-busy="true">
      <div class="skeleton skeleton-head" />
      <div class="skeleton skeleton-block" />
      <div class="skeleton skeleton-block skeleton-block--tall" />
    </div>
    <template v-else>
      <!-- 头部：身份 + 状态 + 操作，一处收齐 -->
      <section class="panel head-panel anim-fade-in-up">
        <div class="head-main">
          <el-button class="back-btn" text @click="goBack">返回列表</el-button>
          <div class="head-title">
            <PageHeader :title="contract?.name || `合同 #${props.id}`" class="head-page-header">
              <template #meta>
                <el-tag :type="statusMeta(contract?.status ?? '').type" effect="dark">
                  {{ statusMeta(contract?.status ?? '').label }}
                </el-tag>
                <el-tag v-if="contract?.isBackfill" type="primary" effect="plain">补录</el-tag>
                <el-tag v-if="contract?.overdue" type="danger" effect="plain">待审批超时</el-tag>
                <el-tag v-if="(contract?.roundNo ?? 0) > 0" type="info" effect="plain">
                  第 {{ contract?.roundNo }} 轮
                </el-tag>
              </template>
            </PageHeader>
          </div>
          <div class="head-meta">
            <span class="meta-item">
              <em>类型</em>{{ contractTypeLabel(contract?.contractTypeKey) || '—' }}
            </span>
            <span class="meta-item">
              <em>编号</em>
              <b v-if="contract?.unifiedNumber" class="value-num">{{ contract.unifiedNumber }}</b>
              <span v-else class="meta-muted">未编号</span>
            </span>
            <span class="meta-item"><em>财年</em>{{ contract?.fiscalYear ?? '—' }}</span>
            <span class="meta-item">
              <em>创建时间</em>{{ formatDateTime(contract?.createdAt) }}
            </span>
          </div>
        </div>
        <div v-if="canOperateContract" class="head-actions" role="group" aria-label="合同操作">
          <template v-if="contract?.status === 'DRAFT'">
            <el-button :loading="actionLoading" @click="openDraftEdit">编辑草稿</el-button>
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
            <el-button :loading="actionLoading" @click="doReject">拒绝确认</el-button>
            <span class="action-hint">
              <template v-if="canActForPending">末方确认后自动编号并落账</template>
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
            <span class="action-hint">需超级管理员审核</span>
          </template>
          <template v-else-if="contract?.status === 'MOD_APPLYING'">
            <template v-if="canReview">
              <el-button type="primary" :loading="actionLoading" @click="openReview('modify', 'approve')">
                通过
              </el-button>
              <el-button type="danger" :loading="actionLoading" @click="openReview('modify', 'reject')">
                驳回
              </el-button>
            </template>
            <span v-else class="action-hint">待超级管理员审核</span>
          </template>
          <template v-else-if="contract?.status === 'MOD_EDITING'">
            <el-button type="primary" :loading="actionLoading" @click="openChangesDialog">
              提交修改
            </el-button>
            <span class="action-hint">超级管理员已批准修改，提交后回滚旧效果并重新落账</span>
          </template>
          <template v-else-if="contract?.status === 'BACKFILL_REVIEW'">
            <template v-if="canReview">
              <el-button type="primary" :loading="actionLoading" @click="openReview('backfill', 'approve')">
                补录通过
              </el-button>
              <el-button type="danger" :loading="actionLoading" @click="openReview('backfill', 'reject')">
                补录驳回
              </el-button>
            </template>
            <span v-else class="action-hint">待超级管理员审核</span>
          </template>
          <span v-else class="action-hint">暂无可用操作</span>
          <el-dropdown trigger="click" class="more-dropdown" @command="onMoreCommand">
            <el-button plain>更多</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-if="contract?.status !== 'CANCELLED'" command="terminate">
                  终止合同
                </el-dropdown-item>
                <el-dropdown-item v-if="canReview" command="rollback">
                  删除（回滚）
                </el-dropdown-item>
                <el-dropdown-item v-if="canReview" command="plain">
                  不回滚删除
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </section>
      <!-- 状态进度轨：一眼看清合同走到哪一步 -->
      <section class="panel track-panel anim-fade-in-up">
        <ol class="status-track">
          <li
            v-for="step in statusTrack"
            :key="step.key"
            class="track-step"
            :class="`is-${step.state}`"
          >
            <span class="track-dot" />
            <span class="track-label">{{ step.label }}</span>
            <span
              v-if="step.key === '参与方确认' && sortedParties.length"
              class="track-count value-num"
            >{{ confirmedPartyCount }}/{{ sortedParties.length }}</span>
          </li>
        </ol>
        <p v-if="trackNote" class="track-note">{{ trackNote }}</p>
      </section>
      <div v-if="loadError" class="notice notice--danger detail-error">
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="load">重试</el-button>
      </div>
      <!-- 主体：左侧内容标签页 + 右侧事实侧栏 -->
      <div class="detail-body">
        <section class="panel main-panel anim-fade-in-up">
          <el-tabs v-model="activeTab" class="detail-tabs">
            <el-tab-pane name="basic" label="合同内容">
              <div class="block-head">
                <h3 class="block-title">参与方确认</h3>
                <span class="block-note">
                  已确认 {{ confirmedPartyCount }}/{{ sortedParties.length }}
                </span>
              </div>
              <div v-if="sortedParties.length" class="party-list">
                <div
                  v-for="(p, i) in sortedParties"
                  :key="p.role"
                  class="party-row"
                  :class="{
                    'party-row--pending': pendingParty && p.role === pendingParty.role,
                  }"
                >
                  <span class="party-order value-num">{{ i + 1 }}</span>
                  <div class="party-main">
                    <div class="party-name">
                      {{ p.companyName || '—' }}
                      <el-tag size="small" effect="plain">
                        {{ partyRoleLabel(contract?.contractTypeKey, p.role) }}
                      </el-tag>
                    </div>
                    <div class="party-sub">
                      <template v-if="p.confirmAt">
                        已确认 · {{ p.confirmedBy || '—' }} · {{ formatDateTime(p.confirmAt) }}
                      </template>
                      <template v-else-if="pendingParty && p.role === pendingParty.role">
                        等待该参与方确认
                      </template>
                      <template v-else>未到确认顺序</template>
                    </div>
                  </div>
                  <el-tag
                    :type="p.confirmAt
                      ? 'success'
                      : pendingParty && p.role === pendingParty.role
                        ? 'warning'
                        : 'info'"
                    size="small"
                    effect="plain"
                  >
                    {{ p.confirmAt
                      ? '已确认'
                      : pendingParty && p.role === pendingParty.role
                        ? '等待中'
                        : '未确认' }}
                  </el-tag>
                </div>
              </div>
              <el-empty v-else :image-size="72" description="暂无参与方" />
              <h3 class="block-title block-title--spaced">输入项</h3>
              <div v-if="inputEntries.length" class="input-grid">
                <div
                  v-for="[key, value] in inputEntries"
                  :key="key"
                  class="input-item"
                  :class="{ 'input-item--list': isListKey(key) }"
                >
                  <span class="input-key">{{ inputLabel(contract?.contractTypeKey, key) }}</span>
                  <div v-if="isListKey(key)" class="input-list">
                    <el-table
                      :data="listRows(key, value)"
                      size="small"
                      border
                      class="input-list-table"
                     stripe>
                      <el-table-column
                        prop="item"
                        :label="listItemLabel(key)"
                        min-width="120"
                      />
                      <el-table-column
                        v-for="sub in listSubFields(key)"
                        :key="sub.key"
                        :label="sub.label || sub.key"
                        width="120"
                        align="right"
                      >
                        <template #default="{ row }">
                          <span class="value-num">{{ row[sub.key] ?? '—' }}</span>
                        </template>
                      </el-table-column>
                      <template #empty>
                        <el-empty :image-size="72" description="清单为空" />
                      </template>
                    </el-table>
                    <div v-if="listTotal(key, value) !== null" class="input-list-total">
                      合计金额：<span class="value-num">{{ listTotal(key, value) }}</span>
                    </div>
                  </div>
                  <span v-else class="input-value value-num">{{ inputDisplay(key, value) }}</span>
                </div>
              </div>
              <el-empty v-else :image-size="72" description="暂无输入项" />
            </el-tab-pane>
            <el-tab-pane v-if="canViewAudit" name="timeline" label="确认时间线">
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
                    <div
                      v-if="node.detail"
                      class="node-detail"
                      :class="{ 'node-detail--confirm': node.type === 'CONFIRM' }"
                    >
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
              <el-empty v-else description="暂无时间线记录"  :image-size="72" />
            </el-tab-pane>
            <el-tab-pane v-if="canViewAudit" name="checks" label="检查记录">
              <el-table :data="checks" border stripe size="small" class="detail-table">
                <template #empty>
                  <el-empty description="暂无检查记录"  :image-size="72" />
                </template>
                <el-table-column label="轮次" width="130" align="center">
                  <template #default="{ row }">
                    <el-tag v-if="row.roundStatus === 'ACTIVE'" type="success" size="small">
                      第 {{ row.roundNo }} 轮·生效
                    </el-tag>
                    <el-tag v-else type="info" size="small">第 {{ row.roundNo }} 轮·历史</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="检查点" width="150">
                  <template #default="{ row }">{{ row.checkpointLabel }}</template>
                </el-table-column>
                <el-table-column label="结果" width="90" align="center">
                  <template #default="{ row }">
                    <el-tag v-if="row.passed" type="success" size="small">通过</el-tag>
                    <el-tag v-else type="danger" size="small">未通过</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="问题清单" min-width="200">
                  <template #default="{ row }">
                    <span v-if="!row.problems || row.problems.length === 0" class="num-empty">无问题</span>
                    <div v-else class="check-problems">
                      <div v-for="(p, i) in row.problems" :key="i" class="check-problem">· {{ p }}</div>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="检查依据" min-width="240">
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
                <el-table-column label="检查人 / 时间" width="200">
                  <template #default="{ row }">
                    {{ row.checkedBy }} · {{ formatDateTime(row.checkedAt) }}
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane v-if="canViewAudit" name="effects" label="效果与账本">
              <div class="block-head">
                <h3 class="block-title">效果审计</h3>
                <span class="block-note">
                  {{ currentEffects.length }} 条 · 仅当前生效轮次（第 {{ contract?.roundNo ?? 0 }} 轮）
                </span>
              </div>
              <el-table
                v-loading="effectsLoading"
                :data="currentEffects"
                border
                stripe
                size="small"
                class="detail-table"
              >
                <template #empty>
                  <el-empty description="暂无落账效果"  :image-size="72" />
                </template>
                <el-table-column label="对象" min-width="140">
                  <template #default="{ row }">
                    <el-tag
                      v-if="row.target === 'REGION'"
                      size="small"
                      type="info"
                      class="effect-target-tag"
                    >
                      区域
                    </el-tag>
                    {{ effectTargetName(row) }}
                  </template>
                </el-table-column>
                <el-table-column label="字段" min-width="120">
                  <template #default="{ row }">{{ fieldLabel(row.fieldKey) }}</template>
                </el-table-column>
                <el-table-column prop="op" label="操作" width="80" align="center">
                  <template #default="{ row }">
                    <el-tag size="small" effect="plain">{{ opLabel(row.op) }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="值" width="100">
                  <template #default="{ row }">{{ toDisplay(row.value) }}</template>
                </el-table-column>
                <el-table-column label="当前链" min-width="190">
                  <template #default="{ row }">
                    <template v-if="row.isCurrent && row.replayBefore !== undefined">
                      <span
                        class="effect-replay"
                        :class="{ 'replay-drift': toDisplay(row.replayBefore) !== toDisplay(row.before) }"
                      >
                        {{ toDisplay(row.replayBefore) }} → {{ toDisplay(row.replayAfter) }}
                      </span>
                      <div
                        v-if="toDisplay(row.replayBefore) !== toDisplay(row.before)"
                        class="replay-tip"
                      >
                        上游已修改
                      </div>
                    </template>
                    <span v-else class="num-empty">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="时间" width="160">
                  <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
                </el-table-column>
              </el-table>
              <template v-if="ledger?.chains?.length">
                <div class="block-head block-head--spaced">
                  <h3 class="block-title">资金账本链</h3>
                  <span class="block-note">当前值 = 字段真实值；括号内为只算合同效果的重演值</span>
                </div>
                <el-collapse class="ledger-collapse">
                  <el-collapse-item
                    v-for="chain in ledger.chains"
                    :key="`${chain.companyId}-${chain.fieldKey}`"
                    :name="`${chain.companyId}-${chain.fieldKey}`"
                  >
                    <template #title>
                      <span class="ledger-title">{{ fieldLabel(chain.fieldKey) }}</span>
                      <span class="ledger-title-sub">
                        {{ companyNameById.get(chain.companyId) || `公司 #${chain.companyId}` }}
                      </span>
                      <span class="ledger-range value-num">
                        {{ toDisplay(chain.initialValue) }}
                        <span class="effect-arrow">⇒</span>
                        {{ toDisplay(chain.currentValue) }}
                        <span
                          v-if="
                            chain.replayValue !== undefined &&
                            toDisplay(chain.replayValue) !== toDisplay(chain.currentValue)
                          "
                          class="ledger-drift"
                        >
                          （合同链重演 {{ toDisplay(chain.replayValue) }}）
                        </span>
                      </span>
                    </template>
                    <el-alert
                      v-if="chain.nonContractChanges && chain.nonContractChanges.length"
                      type="info"
                      :closable="false"
                      show-icon
                      class="ledger-note"
                    >
                      <template #title>
                        有 {{ chain.nonContractChanges.length }} 笔非合同变更（手工修改 / 财年定时器 /
                        公式重算 / 补录同步），最近一笔：
                        {{ chain.nonContractChanges[0]?.sourceLabel }}
                        {{ toDisplay(chain.nonContractChanges[0]?.before) }} →
                        {{ toDisplay(chain.nonContractChanges[0]?.after) }}
                        （{{ chain.nonContractChanges[0]?.operator }}）
                      </template>
                    </el-alert>
                    <el-table :data="chain.nodes" border size="small" class="detail-table" stripe>
                      <el-table-column label="合同" min-width="170">
                        <template #default="{ row }">
                          <span class="ledger-contract">{{ row.unifiedNumber || row.contractName }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column label="效果" width="110">
                        <template #default="{ row }">{{ opLabel(row.op) }} {{ toDisplay(row.value) }}</template>
                      </el-table-column>
                      <el-table-column label="当前账目" min-width="160">
                        <template #default="{ row }">
                          <span class="effect-replay">
                            {{ toDisplay(row.replayBefore) }} → {{ toDisplay(row.replayAfter) }}
                          </span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </el-collapse-item>
                </el-collapse>
              </template>
            </el-tab-pane>
          </el-tabs>
        </section>
        <aside class="panel aside-panel anim-fade-in-up">
          <h3 class="block-title">合同信息</h3>
          <dl class="fact-list">
            <div class="fact">
              <dt>状态</dt>
              <dd>
                <el-tag :type="statusMeta(contract?.status ?? '').type" size="small">
                  {{ statusMeta(contract?.status ?? '').label }}
                </el-tag>
              </dd>
            </div>
            <div v-if="contract?.cancelledAt" class="fact">
              <dt>终止</dt>
              <dd>
                {{ formatDateTime(contract.cancelledAt) }}
                <span class="meta-muted">（{{ contract.cancelledBy || '—' }}）</span>
                <div v-if="contract.cancelReason" class="meta-muted">
                  原因：{{ contract.cancelReason }}
                </div>
              </dd>
            </div>
            <div class="fact">
              <dt>落账轮次</dt>
              <dd class="value-num">第 {{ contract?.roundNo ?? 0 }} 轮</dd>
            </div>
            <div class="fact">
              <dt>参与方确认</dt>
              <dd>
                <span class="value-num">{{ confirmedPartyCount }}/{{ sortedParties.length }}</span>
                <el-progress
                  :percentage="confirmedPercent"
                  :show-text="false"
                  :stroke-width="4"
                  class="fact-progress"
                />
              </dd>
            </div>
            <div v-if="canViewAudit" class="fact">
              <dt>落账效果</dt>
              <dd class="value-num">{{ effects.length }} 条</dd>
            </div>
            <div v-if="contract?.postedAt" class="fact">
              <dt>落账时间</dt>
              <dd>{{ formatDateTime(contract?.postedAt) }}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </template>
    <el-dialog v-model="showModifyDialog" title="申请修改" width="560px" append-to-body>
      <el-form>
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
      width="560px"
      append-to-body
    >
      <el-form>
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
    <el-dialog
      v-model="showChangesDialog"
      :title="changesMode === 'draft' ? '编辑草稿' : '提交修改'"
      width="720px"
      append-to-body
    >
      <el-form>
        <el-form-item
          v-for="f in editFields"
          :key="f.key"
          :label="f.optional ? `${f.label ?? f.key}（选填）` : (f.label ?? f.key)"
          :required="!f.optional"
        >
          <el-input-number
            v-if="f.kind === 'number'"
            :model-value="editNumbers[f.key]"
            :controls="false"
            style="width: 100%"
            @update:model-value="(v: unknown) => setNumber(f.key, v)"
          />
          <el-switch v-else-if="f.kind === 'boolean'" v-model="editBools[f.key]" />
          <el-select
            v-else-if="f.kind === 'text' && isRefType(f.type)"
            v-model="editTexts[f.key]"
            filterable
            clearable
            :placeholder="`选择${f.label || f.key}`"
            style="width: 100%"
          >
            <el-option
              v-for="option in optionsFor(f.type)"
              :key="option.id"
              :label="option.label || option.name"
              :value="option.name"
            />
          </el-select>
          <div v-else-if="f.kind === 'list'" class="list-editor">
            <div
              v-for="(row, index) in editLists[f.key] ?? []"
              :key="index"
              class="list-row"
            >
              <el-select
                v-model="row.item"
                filterable
                clearable
                :placeholder="`选择${f.itemLabel || '明细'}`"
                class="list-item-select"
              >
                <el-option
                  v-for="option in optionsFor(f.type)"
                  :key="option.id"
                  :label="option.label || option.name || `${f.itemLabel || '明细'} #${option.id}`"
                  :value="option.name || `${f.itemLabel || '明细'} #${option.id}`"
                />
              </el-select>
              <el-input-number
                v-for="sub in f.fields ?? []"
                :key="sub.key"
                :model-value="listRowNumber(row, sub.key)"
                :min="sub.min ?? 0"
                :controls="false"
                :placeholder="sub.label || sub.key"
                class="list-qty"
                @update:model-value="(v: unknown) => setListRowNumber(row, sub.key, v)"
              />
              <el-button link type="danger" @click="removeEditListRow(f.key, index)">
                删除
              </el-button>
            </div>
            <el-button size="small" @click="addEditListRow(f.key)">
              + 添加{{ f.itemLabel || '原料' }}
            </el-button>
          </div>
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
          :image-size="72"
          description="该合同暂无可修改的数据字段"
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
/* 清单类输入：整行铺满、标题在上（选择器带 .input-grid 提高优先级，避免被 .input-item 覆盖） */
.input-grid .input-item--list {
  grid-column: 1 / -1;
  display: block;
}
.input-grid .input-item--list .input-key {
  display: block;
  margin-bottom: 6px;
}
.input-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.input-list-table {
  width: 100%;
}
.input-list-total {
  color: var(--color-text-secondary);
  font-size: 12px;
  text-align: right;
}
.list-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.list-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.list-item-select {
  flex: 1;
}
.list-qty {
  width: 120px;
}
.ledger-drift {
  margin-left: 6px;
  color: var(--color-text-tertiary);
  font-weight: 500;
}
.ledger-note {
  margin: 4px 0 10px;
}
.contract-detail-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
// ---------------- 头部 ----------------
.head-panel {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  padding: 16px 20px;
}
.head-main {
  flex: 1 1 420px;
  min-width: 0;
}
.back-btn {
  margin-bottom: 2px;
  margin-left: -8px;
}
.head-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.head-title .page-title {
  margin-bottom: 0;
}
.head-meta {
  display: flex;
  align-items: center;
  gap: 6px 0;
  flex-wrap: wrap;
  color: var(--color-text-primary);
  font-size: var(--font-sm);
}
.meta-item {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 0 14px;
  border-left: 1px solid var(--color-border);
}
.meta-item:first-child {
  padding-left: 0;
  border-left: 0;
}
.meta-item em {
  font-style: normal;
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}
.meta-muted {
  color: var(--color-text-tertiary);
}
.head-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.head-actions .action-hint {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
  order: -1;
}
.more-dropdown {
  margin-left: 4px;
}
// ---------------- 状态进度轨 ----------------
.track-panel {
  padding: 12px 20px 14px;
}
.status-track {
  display: flex;
  align-items: flex-start;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.track-step {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding-right: 10px;
}
.track-step::after {
  content: '';
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  left: 14px;
  right: -6px;
  height: 2px;
  background: var(--color-border);
  border-radius: 2px;
}
.track-step:last-child::after {
  display: none;
}
.track-dot {
  position: relative;
  z-index: 1;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--color-border);
  background: var(--surface-raised);
  flex: none;
}
.track-label {
  position: relative;
  z-index: 1;
  font-size: var(--font-sm);
  color: var(--color-text-tertiary);
  background: var(--color-surface);
  padding-right: 6px;
  white-space: nowrap;
}
.track-count {
  position: relative;
  z-index: 1;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
  background: var(--color-surface);
}
.track-step.is-done .track-dot {
  background: var(--color-primary);
  border-color: var(--color-primary);
}
.track-step.is-done::after {
  background: var(--color-primary);
}
.track-step.is-done .track-label {
  color: var(--color-text-secondary);
}
.track-step.is-active .track-dot {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px rgba(var(--color-primary-rgb), 0.16);
}
.track-step.is-active .track-label,
.track-step.is-active .track-count {
  color: var(--color-text-primary);
  font-weight: 600;
}
.track-note {
  margin: 10px 0 0;
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}
// ---------------- 主体双栏 ----------------
.detail-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 318px;
  gap: 14px;
  align-items: start;
}
.main-panel {
  padding: 6px 20px 20px;
  min-width: 0;
}
.detail-tabs :deep(.el-tabs__header) {
  margin-bottom: 12px;
}
.detail-tabs :deep(.el-tabs__item) {
  height: 44px;
  font-size: var(--font-base);
}
.aside-panel {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
// ---------------- 区块标题 ----------------
.block-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.block-title {
  margin: 0;
  font-size: var(--font-base);
  font-weight: 600;
  color: var(--color-text-primary);
}
.block-title--spaced,
.block-head--spaced {
  margin-top: 20px;
}
.block-note {
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}
// ---------------- 参与方列表 ----------------
.party-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.party-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--surface-raised);
}
.party-row + .party-row {
  border-top: 1px solid var(--color-border);
}
.party-row--pending {
  background: var(--color-warning-soft);
  box-shadow: inset 3px 0 0 var(--color-warning);
}
.party-order {
  width: 20px;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
  font-weight: 600;
  flex: none;
}
.party-main {
  flex: 1;
  min-width: 0;
}
.party-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--color-text-primary);
  flex-wrap: wrap;
}
.party-sub {
  margin-top: 2px;
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
}
// ---------------- 输入项 ----------------
.input-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 8px 12px;
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
// ---------------- 侧栏事实列表 ----------------
.fact-list {
  display: flex;
  flex-direction: column;
  margin: 4px 0 0;
}
.fact {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 0;
  border-bottom: 1px dashed var(--color-border);
}
.fact:last-child {
  border-bottom: 0;
}
.fact dt {
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
  flex: none;
}
.fact dd {
  margin: 0;
  color: var(--color-text-primary);
  font-size: var(--font-sm);
  text-align: right;
  word-break: break-all;
}
.fact-progress {
  margin-top: 6px;
}
// ---------------- 表格与审计 ----------------
.detail-table {
  width: 100%;
}
.effect-target-tag {
  margin-right: 4px;
}
.effect-arrow {
  color: var(--color-text-tertiary);
}
.check-problems {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.check-problem {
  color: var(--color-danger);
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
  color: var(--color-accent);
  font-weight: 600;
}
.replay-drift {
  color: var(--color-warning);
}
.replay-tip {
  color: var(--color-warning);
  font-size: 12px;
  margin-top: 2px;
}
// ---------------- 账本链折叠 ----------------
.ledger-collapse {
  border-top: 1px solid var(--color-border);
}
.ledger-collapse :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 44px;
  padding: 6px 0;
  line-height: 1.5;
}
.ledger-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.ledger-title-sub {
  margin-left: 8px;
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}
.ledger-range {
  margin-left: auto;
  margin-right: 12px;
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}
.ledger-contract {
  font-weight: 500;
}
// ---------------- 时间线 ----------------
.confirm-timeline {
  padding-left: 4px;
}
.node-card {
  background: var(--surface-raised);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
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
// ---------------- 骨架屏 / 错误 ----------------
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
// ---------------- 响应式 ----------------
@media (max-width: 1080px) {
  .detail-body {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 640px) {
  .head-panel {
    padding: 14px 16px;
  }
  .head-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .meta-item {
    padding: 0 10px;
  }
  .status-track {
    flex-wrap: wrap;
    gap: 10px 0;
  }
  .track-step {
    flex: 1 1 45%;
  }
  .track-step::after {
    display: none;
  }
}
</style>