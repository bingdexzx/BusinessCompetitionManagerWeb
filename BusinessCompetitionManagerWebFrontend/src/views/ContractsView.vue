<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createContract, getCompanies, getContractTypes, getContracts, getFiscalYears, syncContracts } from '@/api'
import { useNotifications } from '@/composables/useNotifications'
import type { Company, Contract, ContractType, FiscalYear } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()
const router = useRouter()

// ---------- 状态展示映射（中文标签 + el-tag 颜色） ----------
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

const STATUS_OPTIONS = Object.keys(STATUS_META)

// ---------- 合同列表（服务端分页 + 增量同步） ----------
const contracts = ref<Contract[]>([])
const loading = ref(false)
const statusFilter = ref('')
const keyword = ref('')
/** 服务端分页（2000+ 合同不能整表拉取） */
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
/** 增量游标（上次同步的服务端时间） */
const lastSyncAt = ref('1970-01-01T00:00:00Z')
const syncing = ref(false)

/** 参与方摘要：role:companyName */
function partiesSummary(row: Contract): string {
  if (!row.parties || row.parties.length === 0) return '—'
  return row.parties.map((p) => `${p.role}:${p.companyName || '—'}`).join('、')
}

/** 加载指定页（服务端分页 + 状态/关键字过滤，薄字段响应） */
async function loadPage(nextPage = page.value): Promise<void> {
  loading.value = true
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
    ElMessage.error(errorMessage(e, '加载失败'))
  } finally {
    loading.value = false
  }
}

/** 增量同步：按 updatedAfter 只拉变更，按 id 幂等合并进当前页（WS 信号/同步按钮触发） */
async function loadContracts(full = false): Promise<void> {
  if (full) {
    await loadPage(1) // 全量=重拉当前页（服务端分页）
    return
  }
  syncing.value = true
  try {
    const result = await syncContracts(props.cid, lastSyncAt.value)
    const map = new Map<number, Contract>()
    for (const c of contracts.value) map.set(c.id, c)
    for (const item of result.items) map.set(item.id, item) // 同 id 取新（幂等）
    contracts.value = [...map.values()].sort((a, b) =>
      (b.createdAt ?? '').localeCompare(a.createdAt ?? ''),
    )
    lastSyncAt.value = result.serverTime // 服务端时间做游标，规避客户端时钟偏差
    if (result.hasMore) await loadContracts() // 还有更多变更则续拉
  } catch (e) {
    try {
      await loadPage(page.value) // 增量失败回退当前页重拉
      lastSyncAt.value = new Date().toISOString()
    } catch {
      ElMessage.error(errorMessage(e, '同步失败'))
    }
  } finally {
    syncing.value = false
    loading.value = false
  }
}

/** 过滤条件变化 → 回第 1 页（关键字防抖 300ms） */
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

/** WebSocket 推送到达时增量同步（合同相关通知才触发） */
useNotifications((message) => {
  const payload = message.payload || {}
  const isContractEvent = typeof message.kind === 'string' && message.kind.startsWith('CONTRACT')
  if (isContractEvent || payload.contractId != null) {
    void loadContracts(false)
  }
})

function openDetail(row: Contract): void {
  void router.push(`/competitions/${props.cid}/contracts/${row.id}`)
}

// ---------- 创建合同 ----------
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
const createIsBackfill = ref(false)
const createFiscalYearId = ref<number | null>(null)

const selectedType = computed<ContractType | null>(
  () => contractTypes.value.find((t) => t.key === createTypeKey.value) ?? null,
)

/** 已关闭财年（补录只能选已结束的财年） */
const closedFiscalYears = computed(() => fiscalYears.value.filter((f) => f.status === 'CLOSED'))

function isNumberField(type: string | undefined): boolean {
  return (type ?? '').toUpperCase() === 'NUMBER'
}

function onTypeChange(): void {
  createParties.value = {}
  createTexts.value = {}
  createNumbers.value = {}
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
    ElMessage.error('请选择合同类型')
    return
  }
  // 必填参与方校验
  for (const p of type.partyRoles) {
    if (!p.optional && !createParties.value[p.role]) {
      ElMessage.error(`请选择「${p.label || p.role}」对应的公司`)
      return
    }
  }
  // 必填字段校验
  for (const f of type.inputSchema) {
    const empty = isNumberField(f.type)
      ? createNumbers.value[f.key] === undefined
      : !(createTexts.value[f.key] ?? '').trim()
    if (f.required && empty) {
      ElMessage.error(`请填写「${f.label || f.key}」`)
      return
    }
  }
  if (createIsBackfill.value && !createFiscalYearId.value) {
    ElMessage.error('补录合同必须选择财年')
    return
  }

  const inputs: Record<string, unknown> = {}
  for (const f of type.inputSchema) {
    if (isNumberField(f.type)) {
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
    ElMessage.success(createIsBackfill.value ? '补录合同已创建，待超管审核' : '合同已创建（草稿）')
    await loadContracts()
    if (created?.id) openDetail(created)
  } catch (e) {
    ElMessage.error(errorMessage(e, '操作失败'))
  } finally {
    creating.value = false
  }
}

// ---------- 初始化 ----------
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
    ElMessage.error(errorMessage(e, '操作失败'))
  }
}

onMounted(() => {
  void loadContracts(true) // 首次全量，此后增量
  void loadBaseData()
})

watch(
  () => props.cid,
  () => {
    contracts.value = []
    lastSyncAt.value = '1970-01-01T00:00:00Z'
    void loadContracts(true)
    void loadBaseData()
  },
)
</script>

<template>
  <div class="contracts-page">
    <div class="page-toolbar">
      <h1 class="page-title">合同工作台</h1>
      <div class="page-actions">
        <el-select
          v-model="statusFilter"
          clearable
          placeholder="按状态筛选"
          style="width: 160px"
        >
          <el-option
            v-for="s in STATUS_OPTIONS"
            :key="s"
            :label="statusMeta(s).label"
            :value="s"
          />
        </el-select>
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索名称 / 统一编号"
          style="width: 220px"
        />
        <el-button :loading="syncing" @click="loadContracts(false)">同步</el-button>
        <el-button type="primary" @click="openCreate">创建合同</el-button>
      </div>
    </div>

    <el-table
      v-loading="loading"
      :data="contracts"
      border
      stripe
      class="clickable-table"
      style="width: 100%"
      @row-click="openDetail"
    >
      <template #empty>
        <el-empty description="暂无合同" />
      </template>
      <el-table-column prop="name" label="合同名称" min-width="180">
        <template #default="{ row }">
          <span class="contract-name">{{ row.name || `合同 #${row.id}` }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="contractTypeKey" label="类型" min-width="130" />
      <el-table-column label="统一编号" min-width="160">
        <template #default="{ row }">
          <span v-if="row.unifiedNumber" class="unified-number">{{ row.unifiedNumber }}</span>
          <span v-else class="num-empty">未编号</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="130" align="center">
        <template #default="{ row }">
          <el-tag :type="statusMeta(row.status).type">{{ statusMeta(row.status).label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="轮次" width="70" align="center">
        <template #default="{ row }">{{ row.roundNo }}</template>
      </el-table-column>
      <el-table-column label="补录" width="80" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.isBackfill" type="warning" size="small">补录</el-tag>
          <span v-else class="num-empty">—</span>
        </template>
      </el-table-column>
      <el-table-column label="财年" width="80" align="center">
        <template #default="{ row }">{{ row.fiscalYear ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="参与方" min-width="220">
        <template #default="{ row }">
          <span class="party-summary">{{ partiesSummary(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
      </el-table-column>
    </el-table>

    <!-- 服务端分页（2000+ 合同只渲染当前页 50 行） -->
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

    <!-- 创建合同 -->
    <el-dialog v-model="showCreate" title="创建合同" width="640px" append-to-body>
      <el-form label-position="top">
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
              :label="`${t.name}${t.numberPrefix ? `（${t.numberPrefix}）` : ''}`"
              :value="t.key"
            />
          </el-select>
        </el-form-item>

        <!-- 类型结构摘要：编号前缀 / 参与方角色 / 数据字段 -->
        <div v-if="selectedType" class="type-summary">
          <div>
            <b>编号前缀：</b>{{ selectedType.numberPrefix || '—' }}
          </div>
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
              placeholder="选择公司"
              style="width: 100%"
            >
              <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </el-form-item>

          <el-divider>合同数据</el-divider>
          <el-form-item
            v-for="f in selectedType.inputSchema"
            :key="f.key"
            :required="Boolean(f.required)"
            :label="`${f.label || f.key}${f.min !== undefined ? `（最小值 ${f.min}）` : ''}`"
          >
            <el-input-number
              v-if="isNumberField(f.type)"
              :model-value="createNumbers[f.key]"
              :min="f.min"
              :controls="false"
              style="width: 100%"
              @update:model-value="(v: unknown) => (createNumbers[f.key] = typeof v === 'number' ? v : undefined)"
            />
            <el-input v-else v-model="createTexts[f.key]" :placeholder="`请输入${f.label || f.key}`" />
          </el-form-item>

          <el-divider>补录</el-divider>
          <el-form-item>
            <el-checkbox v-model="createIsBackfill">补录合同（需超管审核）</el-checkbox>
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
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.page-toolbar .page-title {
  margin-bottom: 0;
}
.page-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.clickable-table :deep(.el-table__row) {
  cursor: pointer;
}

.contract-name {
  font-weight: 600;
  color: var(--color-text-primary);
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
</style>
