<script setup lang="ts">
// 数据管理页：比赛级基础数据（燃料/仓库/载具/地图/原料/产品/零件/基建/科技树/生产线）通用 CRUD
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import * as api from '@/api'
import type { BasedataRow, BasedataTable } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { toDisplay } from '@/utils/format'

const props = defineProps<{ cid: string }>()
const auth = useAuthStore()

/** 系统超管或本比赛超管：可新增/编辑/删除（其余只读） */
const canManage = computed(
  () =>
    auth.isSuperuser ||
    auth.memberships.some((m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN'),
)

// ---------- 字段配置（name/notes/code 通用，其余按类型） ----------
interface FieldConfig {
  key: string
  label: string
  kind: 'text' | 'number'
  required?: boolean
  width?: number
  minWidth?: number
  placeholder?: string
}

interface TableConfig {
  key: BasedataTable
  label: string
  fields: FieldConfig[]
}

const CSV_TIP = '多个用逗号分隔'

const CODE: FieldConfig = { key: 'code', label: '编码', kind: 'text', required: true, width: 120 }
const NAME: FieldConfig = {
  key: 'name',
  label: '名称',
  kind: 'text',
  required: true,
  minWidth: 130,
}
const NOTES: FieldConfig = { key: 'notes', label: '备注', kind: 'text', minWidth: 140 }

function txt(key: string, label: string, placeholder?: string): FieldConfig {
  return { key, label, kind: 'text', width: 120, placeholder }
}
function num(key: string, label: string): FieldConfig {
  return { key, label, kind: 'number', width: 110 }
}

const FUELS: TableConfig = {
  key: 'fuels',
  label: '基础数据/燃料',
  fields: [CODE, NAME, txt('unit', '单位'), num('energyValue', '热值'), num('price', '单价'), NOTES],
}

const TABLES: TableConfig[] = [
  FUELS,
  {
    key: 'warehouses',
    label: '仓库',
    fields: [CODE, NAME, num('capacity', '容量'), txt('regionCode', '所在地区'), NOTES],
  },
  {
    key: 'vehicles',
    label: '载具',
    fields: [
      CODE,
      NAME,
      txt('vehicleType', '类型'),
      num('loadCapacity', '载重'),
      num('speed', '速度'),
      txt('fuelCode', '燃料编码'),
      num('fuelConsumption', '油耗'),
      NOTES,
    ],
  },
  {
    key: 'maps',
    label: '地图',
    fields: [
      CODE,
      NAME,
      txt('regionType', '地区类型'),
      txt('adjacentCodes', '相邻地区', CSV_TIP),
      num('distance', '距离'),
      NOTES,
    ],
  },
  {
    key: 'materials',
    label: '原料',
    fields: [CODE, NAME, txt('unit', '单位'), num('basePrice', '基础价格'), NOTES],
  },
  {
    key: 'products',
    label: '产品',
    fields: [CODE, NAME, txt('unit', '单位'), num('basePrice', '基础价格'), NOTES],
  },
  {
    key: 'parts',
    label: '零件',
    fields: [
      CODE,
      NAME,
      txt('unit', '单位'),
      num('basePrice', '基础价格'),
      txt('compatibleTypes', '适配类型', CSV_TIP),
      NOTES,
    ],
  },
  {
    key: 'infrastructures',
    label: '基建',
    fields: [
      CODE,
      NAME,
      txt('infraType', '类型'),
      num('buildCost', '建造成本'),
      num('maintenanceCost', '维护成本'),
      NOTES,
    ],
  },
  {
    key: 'tech_trees',
    label: '科技树',
    fields: [
      CODE,
      NAME,
      num('tier', '层级'),
      txt('prerequisiteCodes', '前置科技', CSV_TIP),
      num('researchCost', '研发成本'),
      NOTES,
    ],
  },
  {
    key: 'production_lines',
    label: '生产线',
    fields: [CODE, NAME, num('capacity', '产能'), num('buildCost', '建造成本'), NOTES],
  },
]

// ---------- 列表（前端关键字过滤 code/name + 前端分页） ----------
const activeTable = ref<BasedataTable>('fuels')
const currentTable = computed(() => TABLES.find((t) => t.key === activeTable.value) ?? FUELS)
const currentFields = computed(() => currentTable.value.fields)

const rows = ref<BasedataRow[]>([])
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)

const filteredRows = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((row) => {
    const code = String(row.code ?? '').toLowerCase()
    const name = String(row.name ?? '').toLowerCase()
    return code.includes(q) || name.includes(q)
  })
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredRows.value.slice(start, start + pageSize.value)
})

function cell(value: unknown): string {
  return toDisplay(value)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await api.getBasedata(props.cid, activeTable.value, { page: 1, pageSize: 500 })
    rows.value = res.items
  } catch (err) {
    rows.value = []
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    loading.value = false
  }
}

function resetAndLoad(): void {
  keyword.value = ''
  page.value = 1
  void load()
}

// ---------- 新增 / 编辑弹窗（动态表单） ----------
const showForm = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const formRef = ref<FormInstance>()
const form = ref<Record<string, string | number | undefined>>({})

const rules = computed<FormRules>(() => {
  const next: FormRules = {}
  for (const f of currentFields.value) {
    if (f.required) next[f.key] = [{ required: true, message: `请填写${f.label}`, trigger: 'blur' }]
  }
  return next
})

function toNum(value: string | number | undefined): number | undefined {
  if (value === undefined || value === '') return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

function toStr(value: string | number | undefined): string {
  return value === undefined ? '' : String(value)
}

function setText(key: string, value: string): void {
  form.value[key] = value
}

function setNum(key: string, value: number | undefined): void {
  form.value[key] = value
}

function openCreate(): void {
  editingId.value = null
  const next: Record<string, string | number | undefined> = {}
  for (const f of currentFields.value) next[f.key] = f.kind === 'number' ? undefined : ''
  form.value = next
  showForm.value = true
}

function openEdit(row: BasedataRow): void {
  editingId.value = row.id
  const next: Record<string, string | number | undefined> = {}
  for (const f of currentFields.value) {
    const raw = row[f.key]
    next[f.key] =
      f.kind === 'number'
        ? raw === null || raw === undefined || raw === ''
          ? undefined
          : Number(raw)
        : raw === null || raw === undefined
          ? ''
          : String(raw)
  }
  form.value = next
  showForm.value = true
}

/** 只提交当前类型配置的字段 */
function buildPayload(): Partial<BasedataRow> {
  const payload: Partial<BasedataRow> = {}
  for (const f of currentFields.value) {
    const v = form.value[f.key]
    if (f.kind === 'number') {
      payload[f.key] = v === undefined || v === '' ? null : Number(v)
    } else {
      payload[f.key] = typeof v === 'string' ? v.trim() : (v ?? '')
    }
  }
  return payload
}

async function submitForm(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = buildPayload()
    if (editingId.value == null) {
      await api.createBasedataRow(props.cid, activeTable.value, payload)
      ElMessage.success('已新增')
    } else {
      await api.updateBasedataRow(props.cid, activeTable.value, editingId.value, payload)
      ElMessage.success('已保存')
    }
    showForm.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    saving.value = false
  }
}

// ---------- 删除 ----------
async function removeRow(row: BasedataRow): Promise<void> {
  const label = String(row.name || row.code || row.id)
  try {
    await ElMessageBox.confirm(`确定删除「${label}」？`, '删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return // 用户取消
  }
  try {
    await api.deleteBasedataRow(props.cid, activeTable.value, row.id)
    ElMessage.success('已删除')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}

// ---------- 初始化 ----------
onMounted(() => void load())
watch(activeTable, resetAndLoad)
watch(() => props.cid, resetAndLoad)
watch(keyword, () => {
  page.value = 1
})
watch(pageSize, () => {
  page.value = 1
})
</script>

<template>
  <div class="basedata-page">
    <div class="page-toolbar">
      <h1 class="page-title">数据管理</h1>
      <div class="page-actions">
        <el-input
          v-model="keyword"
          placeholder="搜索编码/名称"
          clearable
          class="search-input"
        />
        <el-button v-if="canManage" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon>
          <span>新增</span>
        </el-button>
      </div>
    </div>

    <el-card shadow="never">
      <!-- 10 类基础数据切换 -->
      <el-tabs v-model="activeTable" class="type-tabs">
        <el-tab-pane v-for="t in TABLES" :key="t.key" :name="t.key" :label="t.label" />
      </el-tabs>

      <!-- 通用 CRUD 表格 -->
      <el-table v-loading="loading" :data="pagedRows" border stripe empty-text="暂无数据">
        <el-table-column
          v-for="f in currentFields"
          :key="f.key"
          :label="f.label"
          :width="f.width"
          :min-width="f.minWidth"
        >
          <template #default="{ row }">{{ cell(row[f.key]) }}</template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" link type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        class="pager"
        background
        layout="total, sizes, prev, pager, next"
        :total="filteredRows.length"
        :page-sizes="[10, 20, 50]"
      />
    </el-card>

    <!-- 新增 / 编辑弹窗（动态表单） -->
    <el-dialog
      v-model="showForm"
      :title="(editingId == null ? '新增' : '编辑') + currentTable.label"
      width="520px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px" @submit.prevent>
        <el-form-item v-for="f in currentFields" :key="f.key" :label="f.label" :prop="f.key">
          <el-input-number
            v-if="f.kind === 'number'"
            :model-value="toNum(form[f.key])"
            :placeholder="'请输入' + f.label"
            :controls="false"
            style="width: 100%"
            @update:model-value="setNum(f.key, $event)"
          />
          <el-input
            v-else
            :model-value="toStr(form[f.key])"
            :placeholder="f.placeholder || '请输入' + f.label"
            maxlength="200"
            @update:model-value="setText(f.key, $event)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showForm = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
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
  gap: 8px;
  flex-shrink: 0;
}

.search-input {
  width: 220px;
}

.type-tabs {
  margin-bottom: 4px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
