<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useListOptions } from '@/composables/useListOptions'
import {
  createContract,
  getCompanies,
  getContractTypes,
  getContracts,
  getFiscalYears,
  syncContracts,
} from '@/api'
import { subscribeCompetition, useNotifications, useResourceRefresh } from '@/composables/useNotifications'
import type { Company, Contract, ContractType, FiscalYear } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()
const router = useRouter()

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

// 状态色只作视觉分组，文案与业务值原样保留
type StatusTone = 'neutral' | 'pending' | 'active' | 'done' | 'alert'

const TAG_TONE: Record<TagType, StatusTone> = {
  info: 'neutral',
  warning: 'pending',
  primary: 'active',
  success: 'done',
  danger: 'alert',
}

function statusTone(status: string): StatusTone {
  return TAG_TONE[statusMeta(status).type]
}

const STATUS_OPTIONS = Object.keys(STATUS_META)

const contracts = ref<Contract[]>([])
const loading = ref(false)
const loaded = ref(false)
const loadError = ref('')
const initialLoading = computed(() => !loaded.value)
const statusFilter = ref('')
const keyword = ref('')
// 2000+ 合同走服务端分页，不能整表拉取
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
// 增量游标用服务端时间，规避客户端时钟偏差
const lastSyncAt = ref('1970-01-01T00:00:00Z')
const syncing = ref(false)

function partiesSummary(row: Contract): string {
  if (!row.parties || row.parties.length === 0) return '—'
  return row.parties
    .map((p) => `${partyRoleLabel(row.contractTypeKey, p.role)}：${p.companyName || '—'}`)
    .join('、')
}

/** 参与方角色 → 中文名（插件 PARTY_ROLES[].label，未知回退角色键） */
function partyRoleLabel(typeKey: string | null | undefined, role: string | null | undefined): string {
  const raw = String(role ?? '')
  if (!raw) return ''
  const row = contractTypes.value
    .find((t) => t.key === typeKey)
    ?.partyRoles?.find((item) => item.role === raw)
  return row?.label || raw
}

async function loadPage(nextPage = page.value): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const result = await getContracts(props.cid, {
      page: nextPage,
      pageSize: pageSize.value,
      status: statusFilter.value || undefined,
      q: keyword.value.trim() || undefined,
    })
    contracts.value = result.items
    total.value = result.total
    page.value = result.page
    lastSyncAt.value = new Date().toISOString()
  } catch (e) {
    loadError.value = errorMessage(e, '加载失败')
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    loading.value = false
    loaded.value = true
  }
}

// 按 updatedAfter 只拉变更，按 id 幂等合并进当前页
async function loadContracts(full = false): Promise<void> {
  if (full) {
    await loadPage(1)
    return
  }
  syncing.value = true
  try {
    const result = await syncContracts(props.cid, lastSyncAt.value)
    const map = new Map<number, Contract>()
    for (const c of contracts.value) map.set(c.id, c)
    for (const item of result.items) map.set(item.id, item)
    contracts.value = [...map.values()].sort((a, b) =>
      (b.createdAt ?? '').localeCompare(a.createdAt ?? ''),
    )
    lastSyncAt.value = result.serverTime
    if (result.hasMore) await loadContracts()
  } catch (e) {
    try {
      await loadPage(page.value)
      lastSyncAt.value = new Date().toISOString()
    } catch {
      ElMessage.error(errorMessage(e, '同步失败'))
    }
  } finally {
    syncing.value = false
    loading.value = false
  }
}

// 筛选变化回第 1 页，关键字防抖 300ms
let keywordTimer: ReturnType<typeof setTimeout> | null = null
watch(statusFilter, () => void loadPage(1))
watch(keyword, () => {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => void loadPage(1), 300)
})


function onPageChange(next: number): void {
  void loadPage(next)
}
function onSizeChange(size: number): void {
  pageSize.value = size
  void loadPage(1)
}

useNotifications((message) => {
  const payload = message.payload || {}
  const isContractEvent = typeof message.kind === 'string' && message.kind.startsWith('CONTRACT')
  if (isContractEvent || payload.contractId != null) {
    // 整页重拉：合同状态变化/删除都要反映出来（增量同步只 upsert，删不掉行）
    void loadPage(page.value)
  }
})

// 合同/公司/财年等变更后 400ms 去抖增量刷新
const REFRESH_RESOURCES = ['contracts', 'companies', 'fiscal-years', 'basedata', 'packages']
useResourceRefresh(REFRESH_RESOURCES, () => {
  // 资源变更（含别处删除合同）→ 重拉当前页，保证删除也能同步到界面
  void loadPage(page.value)
  void loadBaseData()
})

function openDetail(row: Contract): void {
  void router.push(`/competitions/${props.cid}/contracts/${row.id}`)
}

const showCreate = ref(false)
const creating = ref(false)
const contractTypes = ref<ContractType[]>([])
const companies = ref<Company[]>([])
const fiscalYears = ref<FiscalYear[]>([])

const createTypeKey = ref('')
const createName = ref('')
const createParties = ref<Record<string, number | null>>({})
const createTexts = ref<Record<string, string>>({})
const createNumbers = ref<Record<string, number | undefined>>({})
const createBools = ref<Record<string, boolean>>({})
/** LIST 类型输入（如原料清单）：key → 行数组；行内除 item 外的键由 schema.fields 决定 */
interface ListRow {
  item: string
  [key: string]: unknown
}
const createLists = ref<Record<string, ListRow[]>>({})
// 清单行选项按引用表取（原料/零件/产品/地图节点），不再写死原料
const { optionsFor, ensure: ensureListOptions } = useListOptions(Number(props.cid))

function isListField(type: string | undefined): boolean {
  return String(type ?? '').toUpperCase().startsWith('LIST')
}

/** REF:<表> 输入项：用下拉选条目（公司 / 产品 / 地点 / 城市 / 区域…） */
function isRefField(type: string | undefined): boolean {
  return String(type ?? '').toUpperCase().startsWith('REF')
}

function listTable(type: string | undefined): string {
  return String(type ?? '').split(':')[1]?.trim().toLowerCase() || 'materials'
}

function refTable(type: string | undefined): string {
  return (String(type ?? '').split(':')[1] ?? '').trim().toLowerCase()
}

function emptyListRow(): ListRow {
  return { item: '' }
}

function addListRow(key: string): void {
  const rows = createLists.value[key] ?? []
  rows.push(emptyListRow())
  createLists.value = { ...createLists.value, [key]: rows }
}

/** 行内数值字段（数量、单价…） */
function listRowNumber(row: ListRow, fieldKey: string): number | undefined {
  const value = row[fieldKey]
  return typeof value === 'number' ? value : undefined
}

function setListRowNumber(row: ListRow, fieldKey: string, value: unknown): void {
  row[fieldKey] = typeof value === 'number' ? value : undefined
}

function removeListRow(key: string, index: number): void {
  const rows = createLists.value[key] ?? []
  rows.splice(index, 1)
  createLists.value = { ...createLists.value, [key]: rows }
}
const createIsBackfill = ref(false)
const createFiscalYearId = ref<number | null>(null)

const selectedType = computed<ContractType | null>(
  () => contractTypes.value.find((t) => t.key === createTypeKey.value) ?? null,
)

// 合同类型键 → 中文名（列表「类型」列不显示 loan/purchase 这类键）
function typeLabel(key: string | null | undefined): string {
  const raw = String(key ?? '')
  if (!raw) return '—'
  return contractTypes.value.find((t) => t.key === raw)?.name || raw
}

// 补录只能选已结束财年
const closedFiscalYears = computed(() => fiscalYears.value.filter((f) => f.status === 'CLOSED'))

function isNumberField(type: string | undefined): boolean {
  return (type ?? '').toUpperCase() === 'NUMBER'
}

/** BOOLEAN / BOOL：用开关录入 */
function isBoolField(type: string | undefined): boolean {
  const t = (type ?? '').toUpperCase()
  return t === 'BOOLEAN' || t === 'BOOL'
}

function onTypeChange(): void {
  createParties.value = {}
  createTexts.value = {}
  createNumbers.value = {}
  createBools.value = {}
  createLists.value = {}
  // 按所选类型的引用表预加载选项（清单与 REF 下拉都用同一套）
  for (const f of selectedType.value?.inputSchema ?? []) {
    if (isListField(f.type)) void ensureListOptions(listTable(f.type))
    else if (isRefField(f.type)) void ensureListOptions(refTable(f.type))
  }
}

function openCreate(): void {
  createTypeKey.value = ''
  createName.value = ''
  createIsBackfill.value = false
  createFiscalYearId.value = null
  onTypeChange()
  showCreate.value = true
}

async function submitCreate(): Promise<void> {
  const type = selectedType.value
  if (!type) {
    ElMessage.warning('请选择合同类型')
    return
  }
  for (const p of type.partyRoles) {
    if (!p.optional && !createParties.value[p.role]) {
      ElMessage.warning(`请选择「${p.label || p.role}」对应的公司`)
      return
    }
  }
  // 2026-11 决策：合同输入项一律必填（`optional: true` 的清单除外，但整张合同至少要一行）
  let listRowsTotal = 0
  for (const f of type.inputSchema) {
    if (isListField(f.type)) {
      const rows = createLists.value[f.key] ?? []
      listRowsTotal += rows.filter((row) => row.item).length
      if (!rows.length) {
        if (f.optional) continue
        ElMessage.warning(`请添加「${f.label || f.key}」`)
        return
      }
      for (const row of rows) {
        if (!row.item) {
          ElMessage.warning(`「${f.label || f.key}」有未选择${f.itemLabel || '明细'}的行`)
          return
        }
        for (const sub of f.fields ?? []) {
          if (listRowNumber(row, sub.key) === undefined) {
            ElMessage.warning(`「${f.label || f.key}」有未填写${sub.label || sub.key}的行`)
            return
          }
        }
      }
      continue
    }
    if (isBoolField(f.type)) continue
    const empty = isNumberField(f.type)
      ? createNumbers.value[f.key] === undefined
      : !(createTexts.value[f.key] ?? '').trim()
    if (empty) {
      ElMessage.warning(`请输入「${f.label || f.key}」`)
      return
    }
  }
  if (type.inputSchema.some((f) => f.optional && isListField(f.type)) && listRowsTotal === 0) {
    ElMessage.warning('至少填写一项采购清单')
    return
  }
  if (createIsBackfill.value && !createFiscalYearId.value) {
    ElMessage.warning('补录合同必须选择财年')
    return
  }

  const inputs: Record<string, unknown> = {}
  for (const f of type.inputSchema) {
    if (isListField(f.type)) {
      inputs[f.key] = (createLists.value[f.key] ?? []).map((row) => {
        const record: Record<string, unknown> = { item: row.item }
        for (const sub of f.fields ?? []) record[sub.key] = row[sub.key]
        return record
      })
      continue
    }
    if (isBoolField(f.type)) {
      inputs[f.key] = createBools.value[f.key] === true
    } else if (isNumberField(f.type)) {
      if (createNumbers.value[f.key] !== undefined) inputs[f.key] = createNumbers.value[f.key]
    } else {
      const v = (createTexts.value[f.key] ?? '').trim()
      if (v) inputs[f.key] = v
    }
  }
  const parties = type.partyRoles
    .filter((p) => createParties.value[p.role] != null)
    .map((p) => ({ role: p.role, companyId: createParties.value[p.role] as number }))

  creating.value = true
  try {
    const created = await createContract(props.cid, {
      contractTypeKey: type.key,
      pluginVersion: type.version,
      name: createName.value.trim() || undefined,
      parties,
      inputs,
      isBackfill: createIsBackfill.value || undefined,
      fiscalYearId: createIsBackfill.value ? (createFiscalYearId.value as number) : undefined,
    })
    showCreate.value = false
    ElMessage.success(createIsBackfill.value ? '补录合同已创建，待超级管理员审核' : '合同已创建（草稿）')
    await loadContracts()
    if (created?.id) openDetail(created)
  } catch (e) {
    ElMessage.error(errorMessage(e, '保存失败'))
  } finally {
    creating.value = false
  }
}

async function loadBaseData(): Promise<void> {
  try {
    const [types, comps, fys] = await Promise.all([
      getContractTypes(props.cid),
      getCompanies(props.cid),
      getFiscalYears(props.cid),
    ])
    contractTypes.value = types
    companies.value = comps
    fiscalYears.value = fys
  } catch (e) {
    ElMessage.error(errorMessage(e, '加载失败'))
  }
}

onMounted(() => {
  // 订阅资源广播；重连自动恢复，断线按 seq 重放
  subscribeCompetition(props.cid)
  // 首次全量，此后增量
  void loadContracts(true)
  void loadBaseData()
})

watch(
  () => props.cid,
  () => {
    contracts.value = []
    lastSyncAt.value = '1970-01-01T00:00:00Z'
    subscribeCompetition(props.cid)
    void loadContracts(true)
    void loadBaseData()
  },
)
</script>

<template>
  <div class="contracts-page page">
    <div class="page-toolbar">
      <PageHeader title="合同工作台">
        <template #actions>
      <div class="page-actions">
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索名称 / 统一编号"
          class="filter-search"
        />
        <el-select
          v-model="statusFilter"
          clearable
          placeholder="按状态筛选"
          class="filter-status"
        >
          <el-option
            v-for="s in STATUS_OPTIONS"
            :key="s"
            :label="statusMeta(s).label"
            :value="s"
          />
        </el-select>
        <span class="filters-divider" aria-hidden="true" />
        <el-button :loading="syncing" @click="loadContracts(false)">同步</el-button>
        <el-button type="primary" @click="openCreate">创建合同</el-button>
      </div>
        </template>
      </PageHeader>
    </div>

    <div v-if="loadError" class="notice notice--danger contracts-error">
      <span>{{ loadError }}</span>
      <el-button link type="primary" @click="loadPage(page)">重试</el-button>
    </div>

    <div v-if="initialLoading" class="skeleton-table panel" aria-busy="true">
      <div v-for="n in 8" :key="n" class="skeleton skeleton-line skeleton-row" />
    </div>

    <template v-else>
      <div class="table-block anim-stagger">
        <el-table
          v-loading="loading"
          :data="contracts"
          border
          stripe
          class="clickable-table"
          style="width: 100%"
          @row-click="openDetail"
         size="small">
          <template #empty>
            <el-empty description="暂无合同"  :image-size="72" />
          </template>
          <el-table-column prop="name" label="合同名称" min-width="160">
            <template #default="{ row }">
              <span class="contract-name">{{ row.name || `合同 #${row.id}` }}</span>
            </template>
          </el-table-column>
          <el-table-column label="类型" min-width="118">
            <template #default="{ row }">{{ typeLabel(row.contractTypeKey) }}</template>
          </el-table-column>
          <el-table-column label="统一编号" min-width="148">
            <template #default="{ row }">
              <span v-if="row.unifiedNumber" class="unified-number value-num">
                {{ row.unifiedNumber }}
              </span>
              <span v-else class="num-empty">未编号</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="150" align="center">
            <template #default="{ row }">
              <span class="status-pill" :class="`tone-${statusTone(row.status)}`">
                {{ statusMeta(row.status).label }}
              </span>
              <el-tag
                v-if="row.overdue"
                size="small"
                type="danger"
                effect="plain"
                class="overdue-tag"
              >
                超时
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="轮次" width="70" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ row.roundNo }}</span>
            </template>
          </el-table-column>
          <el-table-column label="补录" width="74" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.isBackfill" type="warning" size="small">补录</el-tag>
              <span v-else class="num-empty">—</span>
            </template>
          </el-table-column>
          <el-table-column label="财年" width="80" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ row.fiscalYear ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="参与方" min-width="190">
            <template #default="{ row }">
              <span class="party-summary">{{ partiesSummary(row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="164">
            <template #default="{ row }">
              <span class="value-num">{{ formatDateTime(row.createdAt) }}</span>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          class="contracts-pager"
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </template>

    <el-dialog v-model="showCreate" title="创建合同" width="720px" append-to-body>
      <el-form>
        <el-form-item label="合同类型" required>
          <el-select
            v-model="createTypeKey"
            filterable
            placeholder="选择合同类型"
            style="width: 100%"
            @change="onTypeChange"
          >
            <el-option
              v-for="t in contractTypes"
              :key="t.key"
              :label="t.name"
              :value="t.key"
            />
          </el-select>
        </el-form-item>

        <div v-if="selectedType" class="type-summary">
          <div>
            <b>参与方角色：</b>
            {{
              selectedType.partyRoles
                .map((p) => `${p.label || p.role}${p.optional ? '（可选）' : ''}`)
                .join('、') || '—'
            }}
          </div>
          <div>
            <b>数据字段：</b>
            {{
              selectedType.inputSchema.map((f) => `${f.label || f.key}（${f.type}）`).join('、') ||
              '无'
            }}
          </div>
        </div>

        <el-form-item label="合同名称">
          <el-input v-model="createName" placeholder="可留空，由系统按类型生成" />
        </el-form-item>

        <template v-if="selectedType">
          <el-divider>参与方</el-divider>
          <el-form-item
            v-for="p in selectedType.partyRoles"
            :key="p.role"
            :required="!p.optional"
            :label="`${p.label || p.role}${p.optional ? '（可选）' : ''}`"
          >
            <el-select
              v-model="createParties[p.role]"
              clearable
              filterable
              placeholder="请选择公司"
              style="width: 100%"
            >
              <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>

          <el-divider>合同数据</el-divider>
          <el-form-item
            v-for="f in selectedType.inputSchema"
            :key="f.key"
            :required="!f.optional"
            :label="`${f.label || f.key}${f.optional ? '（选填）' : ''}${f.min !== undefined ? `（最小值 ${f.min}）` : ''}`"
          >
            <el-input-number
              v-if="isNumberField(f.type)"
              :model-value="createNumbers[f.key]"
              :min="f.min"
              :controls="false"
              style="width: 100%"
              @update:model-value="(v: unknown) => (createNumbers[f.key] = typeof v === 'number' ? v : undefined)"
            />
            <div v-else-if="isListField(f.type)" class="list-editor">
              <div
                v-for="(row, index) in createLists[f.key] ?? []"
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
                <el-button link type="danger" @click="removeListRow(f.key, index)">
                  删除
                </el-button>
              </div>
              <el-button size="small" @click="addListRow(f.key)">
                + 添加{{ f.itemLabel || '明细' }}
              </el-button>
            </div>
            <el-switch
              v-else-if="isBoolField(f.type)"
              v-model="createBools[f.key]"
            />
            <el-select
              v-else-if="isRefField(f.type)"
              v-model="createTexts[f.key]"
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
            <el-input v-else v-model="createTexts[f.key]" :placeholder="`请输入${f.label || f.key}`" />
          </el-form-item>

          <el-divider>补录</el-divider>
          <el-form-item>
            <el-checkbox v-model="createIsBackfill">补录合同（需超级管理员审核）</el-checkbox>
          </el-form-item>
          <el-form-item v-if="createIsBackfill" label="补录财年" required>
            <el-select
              v-model="createFiscalYearId"
              placeholder="选择已结束的财年"
              style="width: 100%"
            >
              <el-option
                v-for="fy in closedFiscalYears"
                :key="fy.id"
                :label="`${fy.year} 财年（已结束）`"
                :value="fy.id"
              />
            </el-select>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
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
.overdue-tag {
  margin-left: 6px;
}

.contracts-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
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
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.filter-search {
  width: 220px;
}

.filter-status {
  width: 150px;
}

.filters-divider {
  width: 1px;
  height: 22px;
  background: var(--color-border);
}

.contracts-error {
  align-items: center;
  justify-content: space-between;
}

.skeleton-table {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px;
}

.skeleton-row {
  height: 18px;
  margin-bottom: 0;
}

.skeleton-row:nth-child(even) {
  width: 82%;
}

/* 整表入场，行内不位移，避免增量同步时整表重放 */
.table-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}

.clickable-table :deep(.el-table__body tr > td.el-table__cell) {
  transition: background-color var(--dur-fast) var(--ease-standard),
    box-shadow var(--dur-fast) var(--ease-standard);
}

.clickable-table :deep(.el-table__body tr:hover > td.el-table__cell:first-child) {
  box-shadow: inset 3px 0 0 var(--color-primary);
}

.clickable-table :deep(.el-table__body tr:hover .contract-name) {
  color: var(--color-primary);
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-xs);
  font-weight: 600;
  line-height: 20px;
  white-space: nowrap;
  color: var(--color-text-primary);

  &::before {
    content: "";
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-text-tertiary);
  }

  &.tone-neutral {
    color: var(--color-text-secondary);
    background: var(--surface-sunken);
  }

  &.tone-pending {
    background: var(--color-warning-soft);

    &::before {
      background: var(--color-warning);
    }
  }

  &.tone-active {
    background: rgba(var(--color-primary-rgb), 0.1);

    &::before {
      background: var(--color-primary);
    }
  }

  &.tone-done {
    background: var(--color-success-soft);

    &::before {
      background: var(--color-success);
    }
  }

  &.tone-alert {
    background: var(--color-danger-soft);

    &::before {
      background: var(--color-danger);
    }
  }
}

.contract-name {
  font-weight: 600;
  color: var(--color-text-primary);
  transition: color var(--dur-fast) var(--ease-standard);
}

.unified-number {
  font-weight: 600;
  color: var(--color-primary);
  letter-spacing: 0.02em;
}

.num-empty {
  color: var(--color-text-tertiary);
}

.party-summary {
  color: var(--el-text-color-regular);
  font-size: var(--font-sm);
}

.contracts-pager {
  justify-content: flex-end;
}

.type-summary {
  background: var(--surface-sunken);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  margin-bottom: 12px;
  font-size: var(--font-sm);
  color: var(--el-text-color-regular);
  line-height: 1.9;

  b {
    color: var(--color-text-secondary);
  }
}

@media (max-width: 1024px) {
  .filter-search {
    width: 180px;
  }

  .filter-status {
    width: 130px;
  }
}

@media (max-width: 640px) {
  .page-actions {
    width: 100%;
    justify-content: flex-start;
  }

  .filter-search,
  .filter-status {
    width: 100%;
  }

  .filters-divider {
    display: none;
  }
}
</style>
