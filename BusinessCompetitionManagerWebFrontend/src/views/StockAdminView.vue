<script setup lang="ts">
// 股票管理页：股票与资金账户的新增/编辑/删除（仅超管可写，其余整页提示）
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import * as api from '@/api'
import type { Company, CompetitionMember, StockAccount, StockAdmin } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useCatalog } from '@/composables/useCatalog'
import { errorMessage } from '@/utils/errors'
import { toDisplay } from '@/utils/format'

const props = defineProps<{ cid: string }>()

// 产业字段目录：PE 绑定字段 / 账户绑定字段显示中文名，不再让管理员填数字 ID
const catalog = useCatalog(() => props.cid)
const auth = useAuthStore()

/** 系统超管或本比赛超管：可新增/编辑/删除（其余整页提示） */
const canManage = computed(
  () =>
    auth.isSuperuser ||
    auth.memberships.some((m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN'),
)

// ---------- 名称解析（关联公司 / 用户） ----------
const companies = ref<Company[]>([])
const members = ref<CompetitionMember[]>([])

function companyName(id: number | null | undefined): string {
  if (id == null) return '—'
  return companies.value.find((c) => c.id === id)?.name ?? `#${id}`
}

function userName(id: number | null | undefined): string {
  if (id == null) return '—'
  const m = members.value.find((x) => x.userId === id)
  return (m && (m.displayName || m.username)) || `#${id}`
}

/** 下拉选项：列表 + 兜底（原值不在列表时补一项，避免只显示裸 id） */
function companyOptions(extra?: number | null): Array<{ id: number; name: string }> {
  const list = companies.value.map((c) => ({ id: c.id, name: c.name }))
  if (extra != null && !list.some((c) => c.id === extra)) list.push({ id: extra, name: `#${extra}` })
  return list
}

/** 产业字段下拉（PE 绑定字段 / 账户绑定字段）：显示中文名而不是字段 ID */
const fieldOptions = computed(() =>
  catalog.fields.value.map((f) => ({
    id: f.id,
    label: f.name && f.name !== f.key ? `${f.name}（${f.key}）` : f.name || f.key,
  })),
)

function fieldLabelById(id: number | null | undefined): string {
  if (id == null) return '—'
  const hit = catalog.fields.value.find((f) => f.id === id)
  return hit ? hit.name || hit.key : `#${id}`
}

function userOptions(extra?: number | null): Array<{ id: number; name: string }> {
  const list = members.value.map((m) => ({ id: m.userId, name: m.displayName || m.username }))
  if (extra != null && !list.some((u) => u.id === extra)) list.push({ id: extra, name: `#${extra}` })
  return list
}

async function loadRefs(): Promise<void> {
  const [c, m] = await Promise.all([
    api.getCompanies(props.cid).catch(() => [] as Company[]),
    api.getCompetitionMembers(props.cid).catch(() => [] as CompetitionMember[]),
  ])
  companies.value = c
  members.value = m
}

// ---------- 数值归一（Decimal 出站可能是字符串） ----------
function toNum(value: string | number | undefined): number | undefined {
  if (value === undefined || value === '') return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

function toStr(value: string | number | undefined): string {
  return value === undefined ? '' : String(value)
}

function num(value: number | string | null | undefined): number | undefined {
  if (value === null || value === undefined || value === '') return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

// ---------- 股票列表（薄字段 + 详情补齐展示字段） ----------
type StockRow = StockAdmin & { changePct?: number; updatedAt?: string }

const stockRows = ref<StockRow[]>([])
const stockLoading = ref(false)

async function loadStocks(): Promise<void> {
  stockLoading.value = true
  try {
    const res = await api.getStocks(props.cid, { page: 1, pageSize: 500 })
    stockRows.value = res.items as unknown as StockRow[]
    void backfillStockDetails()
  } catch (err) {
    stockRows.value = []
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    stockLoading.value = false
  }
}

/** 列表只带薄字段：并发补齐股本/净利润等（失败静默，编辑时仍拉详情） */
async function backfillStockDetails(): Promise<void> {
  const rows = stockRows.value.filter((r) => r.totalShares == null).slice(0, 100)
  for (let i = 0; i < rows.length; i += 8) {
    await Promise.all(
      rows.slice(i, i + 8).map(async (row) => {
        try {
          const detail = (await api.getStock(props.cid, row.code)) as unknown as StockRow
          Object.assign(row, detail)
        } catch {
          /* 展示字段缺失不阻塞 */
        }
      }),
    )
  }
}

// ---------- 资金账户列表 ----------
const accountRows = ref<StockAccount[]>([])
const accountLoading = ref(false)

async function loadAccounts(): Promise<void> {
  accountLoading.value = true
  try {
    const res = await api.getStockAccounts(props.cid)
    accountRows.value = res.items
  } catch (err) {
    accountRows.value = []
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    accountLoading.value = false
  }
}

function load(): void {
  void loadStocks()
  void loadAccounts()
  void loadRefs()
}

// 资源变更实时刷新：股票数据被其他端写入后自动重拉列表/账户/关联项
useResourceRefresh(['stock'], load)

// ---------- 股票新增 / 编辑弹窗 ----------
interface StockForm {
  code: string
  name: string
  totalShares?: number
  initNetProfit?: number
  initPrice?: number
  currentPrice?: number
  industryPe?: number
  currentCarbon?: number
  industryAvgCarbon?: number
  happiness?: number
  companyId?: number
  pbCompanyId?: number
  pbFieldId?: number
  pbRandom?: number
  [key: string]: string | number | undefined
}

interface StockFieldConfig {
  key: string
  label: string
  kind: 'text' | 'number' | 'company' | 'industryField'
  required?: boolean
  placeholder?: string
}

const STOCK_FIELDS: StockFieldConfig[] = [
  { key: 'code', label: '代码', kind: 'text', required: true },
  { key: 'name', label: '名称', kind: 'text', required: true },
  { key: 'totalShares', label: '股本', kind: 'number', required: true },
  { key: 'initNetProfit', label: '净利润', kind: 'number', required: true },
  { key: 'initPrice', label: '发行价', kind: 'number', required: true },
  { key: 'currentPrice', label: '现价', kind: 'number', placeholder: '留空 = 发行价' },
  { key: 'industryPe', label: '行业PE', kind: 'number', placeholder: '随机模式基准 PE' },
  { key: 'currentCarbon', label: '当前碳排', kind: 'number' },
  { key: 'industryAvgCarbon', label: '行业碳排均值', kind: 'number' },
  { key: 'happiness', label: '幸福度', kind: 'number' },
  { key: 'companyId', label: '关联公司', kind: 'company' },
  { key: 'pbCompanyId', label: 'PE 关联公司', kind: 'number', placeholder: '留空为随机 PE' },
  { key: 'pbFieldId', label: 'PE 绑定字段', kind: 'industryField', placeholder: '与 PE 关联公司同填' },
  { key: 'pbRandom', label: '随机PE', kind: 'number', placeholder: '0-20' },
]

function emptyStockForm(): StockForm {
  return { code: '', name: '' }
}

const showStockForm = ref(false)
const stockSaving = ref(false)
const editingCode = ref<string | null>(null)
const stockFormRef = ref<FormInstance>()
const stockForm = reactive<StockForm>(emptyStockForm())

const stockRules: FormRules = {
  code: [{ required: true, message: '请填写代码', trigger: 'blur' }],
  name: [{ required: true, message: '请填写名称', trigger: 'blur' }],
  totalShares: [{ required: true, message: '请填写股本', trigger: 'change' }],
  initNetProfit: [{ required: true, message: '请填写净利润', trigger: 'change' }],
  initPrice: [{ required: true, message: '请填写发行价', trigger: 'change' }],
}

function setText(key: string, value: string): void {
  stockForm[key] = value
}

function setNum(key: string, value: number | undefined): void {
  stockForm[key] = value
}

function openStockCreate(): void {
  editingCode.value = null
  Object.assign(stockForm, emptyStockForm())
  showStockForm.value = true
}

async function openStockEdit(row: StockRow): Promise<void> {
  try {
    const detail = (await api.getStock(props.cid, row.code)) as unknown as StockAdmin
    editingCode.value = detail.code ?? row.code
    stockForm.code = detail.code ?? row.code ?? ''
    stockForm.name = detail.name ?? row.name ?? ''
    stockForm.totalShares = num(detail.totalShares)
    stockForm.initNetProfit = num(detail.initNetProfit)
    stockForm.initPrice = num(detail.initPrice)
    stockForm.currentPrice = num(detail.currentPrice)
    stockForm.industryPe = num(detail.industryPe ?? detail.industryPE)
    stockForm.currentCarbon = num(detail.currentCarbon)
    stockForm.industryAvgCarbon = num(detail.industryAvgCarbon)
    stockForm.happiness = num(detail.happiness)
    stockForm.companyId = detail.companyId ?? undefined
    stockForm.pbCompanyId = detail.pbCompanyId ?? undefined
    stockForm.pbFieldId = detail.pbFieldId ?? undefined
    stockForm.pbRandom = num(detail.pbRandom)
    showStockForm.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}

function buildStockPayload(): Partial<StockAdmin> {
  return {
    code: stockForm.code.trim(),
    name: stockForm.name.trim(),
    totalShares: toNum(stockForm.totalShares),
    initNetProfit: toNum(stockForm.initNetProfit),
    initPrice: toNum(stockForm.initPrice),
    currentPrice: toNum(stockForm.currentPrice),
    industryPe: toNum(stockForm.industryPe),
    currentCarbon: toNum(stockForm.currentCarbon),
    industryAvgCarbon: toNum(stockForm.industryAvgCarbon),
    happiness: toNum(stockForm.happiness),
    companyId: stockForm.companyId ?? null,
    pbCompanyId: toNum(stockForm.pbCompanyId) ?? null,
    pbFieldId: toNum(stockForm.pbFieldId) ?? null,
    pbRandom: toNum(stockForm.pbRandom) ?? null,
  }
}

async function submitStock(): Promise<void> {
  try {
    await stockFormRef.value?.validate()
  } catch {
    return
  }
  stockSaving.value = true
  try {
    const payload = buildStockPayload()
    if (editingCode.value == null) {
      await api.createStock(props.cid, payload)
      ElMessage.success('已新增')
    } else {
      await api.updateStock(props.cid, editingCode.value, payload)
      ElMessage.success('已保存')
    }
    showStockForm.value = false
    load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    stockSaving.value = false
  }
}

async function removeStock(row: StockRow): Promise<void> {
  const label = `${row.name || row.code}（${row.code}）`
  try {
    await ElMessageBox.confirm(`确定删除股票「${label}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await api.deleteStock(props.cid, row.code)
    ElMessage.success('已删除')
    load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}

// ---------- 资金账户新增 / 编辑弹窗 ----------
interface AccountForm {
  name: string
  ownerType: 'USER' | 'COMPANY'
  userId?: number
  companyId?: number
  cashBalance?: number
  bindFieldId?: number
}

const OWNER_LABELS: Record<'USER' | 'COMPANY', string> = { USER: '个人', COMPANY: '公司' }

function ownerLabel(value: unknown): string {
  return value === 'USER' || value === 'COMPANY' ? OWNER_LABELS[value] : toDisplay(value)
}

function emptyAccountForm(): AccountForm {
  return { name: '', ownerType: 'USER' }
}

const showAccountForm = ref(false)
const accountSaving = ref(false)
const editingAccountId = ref<number | null>(null)
const accountFormRef = ref<FormInstance>()
const accountForm = reactive<AccountForm>(emptyAccountForm())

const accountRules = computed<FormRules>(() => ({
  name: [{ required: true, message: '请填写账户名', trigger: 'blur' }],
  userId:
    accountForm.ownerType === 'USER'
      ? [{ required: true, message: '请选择归属用户', trigger: 'change' }]
      : [],
  companyId:
    accountForm.ownerType === 'COMPANY'
      ? [{ required: true, message: '请选择归属公司', trigger: 'change' }]
      : [],
}))

function onOwnerTypeChange(): void {
  accountForm.userId = undefined
  accountForm.companyId = undefined
}

function openAccountCreate(): void {
  editingAccountId.value = null
  Object.assign(accountForm, emptyAccountForm())
  showAccountForm.value = true
}

function openAccountEdit(row: StockAccount): void {
  editingAccountId.value = row.id ?? null
  accountForm.name = row.name
  accountForm.ownerType = row.ownerType === 'COMPANY' ? 'COMPANY' : 'USER'
  accountForm.userId = row.userId ?? undefined
  accountForm.companyId = row.companyId ?? undefined
  accountForm.cashBalance = num(row.cashBalance)
  accountForm.bindFieldId = row.bindFieldId ?? undefined
  showAccountForm.value = true
}

function buildAccountPayload(): Partial<StockAccount> {
  return {
    name: accountForm.name.trim(),
    ownerType: accountForm.ownerType,
    userId: accountForm.ownerType === 'USER' ? (accountForm.userId ?? null) : null,
    companyId: accountForm.ownerType === 'COMPANY' ? (accountForm.companyId ?? null) : null,
    cashBalance: toNum(accountForm.cashBalance),
    bindFieldId: accountForm.bindFieldId ?? null,
  }
}

async function submitAccount(): Promise<void> {
  try {
    await accountFormRef.value?.validate()
  } catch {
    return
  }
  accountSaving.value = true
  try {
    const payload = buildAccountPayload()
    if (editingAccountId.value == null) {
      await api.createStockAccount(props.cid, payload)
      ElMessage.success('已新增')
    } else {
      await api.updateStockAccount(props.cid, editingAccountId.value, payload)
      ElMessage.success('已保存')
    }
    showAccountForm.value = false
    loadAccounts()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    accountSaving.value = false
  }
}

async function removeAccount(row: StockAccount): Promise<void> {
  const label = row.name || (row.id != null ? `#${row.id}` : '')
  try {
    await ElMessageBox.confirm(`确定删除账户「${label}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await api.deleteStockAccount(props.cid, row.id ?? 0)
    ElMessage.success('已删除')
    loadAccounts()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}

// ---------- 初始化 ----------
onMounted(() => {
  if (canManage.value) load()
})
watch(
  () => props.cid,
  () => {
    if (canManage.value) load()
  },
)
</script>

<template>
  <div class="stock-admin-page">
    <div class="page-toolbar">
      <h1 class="page-title">股票管理</h1>
    </div>

    <el-empty v-if="!canManage" description="仅超级管理员可管理股票与账户" />

    <template v-else>
      <!-- 股票管理 -->
      <el-card shadow="never" class="section-card anim-fade-in-up">
        <template #header>
          <div class="card-header">
            <span class="card-title">股票管理</span>
            <div class="card-tools">
              <el-tag v-if="stockRows.length" size="small" type="info" effect="plain">
                共 {{ stockRows.length }} 只
              </el-tag>
              <el-button type="primary" size="small" @click="openStockCreate">
                <el-icon><Plus /></el-icon>
                <span>新增股票</span>
              </el-button>
            </div>
          </div>
        </template>

        <!-- 首屏加载：骨架代替空表，避免「暂无数据」误判 -->
        <div v-if="stockLoading && !stockRows.length" class="table-skeleton">
          <div v-for="i in 6" :key="i" class="skeleton skeleton-line" />
        </div>
        <el-table v-else v-loading="stockLoading" :data="stockRows" border stripe>
          <template #empty>
            <el-empty description="暂无股票数据" :image-size="60" />
          </template>
          <el-table-column label="代码" width="100">
            <template #default="{ row }">{{ toDisplay(row.code) }}</template>
          </el-table-column>
          <el-table-column label="名称" min-width="120">
            <template #default="{ row }">{{ toDisplay(row.name) }}</template>
          </el-table-column>
          <el-table-column label="现价" width="100" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ toDisplay(row.currentPrice) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="发行价" width="100" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ toDisplay(row.initPrice) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="股本" min-width="110" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ toDisplay(row.totalShares) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="净利润" min-width="110" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ toDisplay(row.initNetProfit) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="轮次" width="70" align="center">
            <template #default="{ row }">{{ toDisplay(row.round) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button size="small" link type="primary" @click="openStockEdit(row)">
                  编辑
                </el-button>
                <el-button
                  size="small"
                  link
                  type="danger"
                  class="danger-op"
                  @click="removeStock(row)"
                >
                  删除
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 资金账户管理 -->
      <el-card shadow="never" class="section-card anim-fade-in-up">
        <template #header>
          <div class="card-header">
            <span class="card-title">资金账户管理</span>
            <div class="card-tools">
              <el-tag v-if="accountRows.length" size="small" type="info" effect="plain">
                共 {{ accountRows.length }} 个
              </el-tag>
              <el-button type="primary" size="small" @click="openAccountCreate">
                <el-icon><Plus /></el-icon>
                <span>新增账户</span>
              </el-button>
            </div>
          </div>
        </template>

        <div v-if="accountLoading && !accountRows.length" class="table-skeleton">
          <div v-for="i in 5" :key="i" class="skeleton skeleton-line" />
        </div>
        <el-table v-else v-loading="accountLoading" :data="accountRows" border stripe>
          <template #empty>
            <el-empty description="暂无资金账户" :image-size="60" />
          </template>
          <el-table-column label="账户名" min-width="130">
            <template #default="{ row }">{{ toDisplay(row.name) }}</template>
          </el-table-column>
          <el-table-column label="归属类型" width="90">
            <template #default="{ row }">{{ ownerLabel(row.ownerType) }}</template>
          </el-table-column>
          <el-table-column label="关联公司或用户" min-width="140">
            <template #default="{ row }">
              {{ row.ownerType === 'USER' ? userName(row.userId) : companyName(row.companyId) }}
            </template>
          </el-table-column>
          <el-table-column label="现金余额" min-width="110" align="right">
            <template #default="{ row }">
              <span class="value-num">{{ toDisplay(row.cashBalance) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="绑定字段" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">{{ fieldLabelById(row.bindFieldId) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <el-button size="small" link type="primary" @click="openAccountEdit(row)">
                  编辑
                </el-button>
                <el-button
                  size="small"
                  link
                  type="danger"
                  class="danger-op"
                  @click="removeAccount(row)"
                >
                  删除
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 股票新增 / 编辑弹窗 -->
    <el-dialog
      v-model="showStockForm"
      :title="editingCode == null ? '新增股票' : '编辑股票'"
      width="520px"
      destroy-on-close
    >
      <el-form
        ref="stockFormRef"
        :model="stockForm"
        :rules="stockRules"
        label-width="110px"
        @submit.prevent
      >
        <el-form-item v-for="f in STOCK_FIELDS" :key="f.key" :label="f.label" :prop="f.key">
          <el-select
            v-if="f.kind === 'company'"
            v-model="stockForm.companyId"
            placeholder="选择公司"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="c in companyOptions(stockForm.companyId)"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
          <el-select
            v-else-if="f.kind === 'industryField'"
            :model-value="toNum(stockForm[f.key]) ?? undefined"
            placeholder="选择产业字段"
            clearable
            filterable
            style="width: 100%"
            @update:model-value="setNum(f.key, $event)"
          >
            <el-option v-for="opt in fieldOptions" :key="opt.id" :label="opt.label" :value="opt.id" />
          </el-select>
          <el-input-number
            v-else-if="f.kind === 'number'"
            :model-value="toNum(stockForm[f.key])"
            :placeholder="f.placeholder || '请输入' + f.label"
            :controls="false"
            style="width: 100%"
            @update:model-value="setNum(f.key, $event)"
          />
          <el-input
            v-else
            :model-value="toStr(stockForm[f.key])"
            :placeholder="f.placeholder || '请输入' + f.label"
            maxlength="100"
            @update:model-value="setText(f.key, $event)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showStockForm = false">取消</el-button>
        <el-button type="primary" :loading="stockSaving" @click="submitStock">保存</el-button>
      </template>
    </el-dialog>

    <!-- 资金账户新增 / 编辑弹窗 -->
    <el-dialog
      v-model="showAccountForm"
      :title="editingAccountId == null ? '新增资金账户' : '编辑资金账户'"
      width="520px"
      destroy-on-close
    >
      <el-form
        ref="accountFormRef"
        :model="accountForm"
        :rules="accountRules"
        label-width="110px"
        @submit.prevent
      >
        <el-form-item label="账户名" prop="name">
          <el-input v-model="accountForm.name" placeholder="请输入账户名" maxlength="100" />
        </el-form-item>
        <el-form-item label="归属类型" prop="ownerType">
          <el-radio-group v-model="accountForm.ownerType" @change="onOwnerTypeChange">
            <el-radio-button value="USER">个人</el-radio-button>
            <el-radio-button value="COMPANY">公司</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="accountForm.ownerType === 'USER'" label="归属用户" prop="userId">
          <el-select
            v-model="accountForm.userId"
            placeholder="选择用户"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="u in userOptions(accountForm.userId)"
              :key="u.id"
              :label="u.name"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item v-else label="归属公司" prop="companyId">
          <el-select
            v-model="accountForm.companyId"
            placeholder="选择公司"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="c in companyOptions(accountForm.companyId)"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="现金余额" prop="cashBalance">
          <el-input-number
            v-model="accountForm.cashBalance"
            placeholder="请输入现金余额"
            :controls="false"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="绑定字段" prop="bindFieldId">
          <el-select
            v-model="accountForm.bindFieldId"
            placeholder="选择产业字段（可空）"
            clearable
            filterable
            style="width: 100%"
          >
            <el-option v-for="opt in fieldOptions" :key="opt.id" :label="opt.label" :value="opt.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAccountForm = false">取消</el-button>
        <el-button type="primary" :loading="accountSaving" @click="submitAccount">保存</el-button>
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

.section-card {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.card-title {
  font-weight: 600;
}

/* 工具条分组：主操作与计数收敛到右侧一组，和标题分成两个视觉块 */
.card-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* 行内操作：主次分明，危险操作默认弱化 */
.row-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.section-card :deep(.danger-op) {
  color: var(--color-text-tertiary);
}
.section-card :deep(.danger-op:hover) {
  color: var(--color-danger);
}

/* 首屏骨架行：高度贴近真实行，减少加载完成后的跳动 */
.table-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
.table-skeleton .skeleton-line {
  height: 38px;
  margin-bottom: 0;
}
.table-skeleton .skeleton-line:last-child {
  width: 100%;
}
</style>
