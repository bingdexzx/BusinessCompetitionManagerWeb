<template>
  <div class="company-page page">
    <PageHeader title="公司管理">
      <template #actions>
        <el-input
          v-model="keyword"
          class="search-input"
          placeholder="搜索公司 / 队伍"
          clearable
        />
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>
    <el-alert
      v-if="errorText"
      class="page-error"
      type="error"
      :closable="false"
      show-icon
      :title="errorText"
    >
      <el-button size="small" @click="load">重试</el-button>
    </el-alert>
    <div v-if="!isSuperuser" class="panel">
      <el-empty description="仅超级管理员可查看公司管理"  :image-size="72" />
    </div>
    <template v-else>
      <div class="panel">
        <el-table
          v-loading="loading"
          :data="filteredCompanies"
          stripe
          size="small"
          @row-click="openCompany"
         border>
        <template #empty>
          <el-empty description="暂无已分配公司" :image-size="72" />
        </template>
          <el-table-column prop="name" label="公司名称" min-width="160" show-overflow-tooltip />
          <el-table-column label="产业" width="140">
            <template #default="{ row }">{{ industryLabel(row.industryKey) }}</template>
          </el-table-column>
          <el-table-column label="队伍" min-width="140">
            <template #default="{ row }">{{ row.teamName || (row.teamId ? `#${row.teamId}` : '—') }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" width="170">
            <template #default="{ row }">{{ row.createdAt ? formatDateTime(row.createdAt) : '—' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click.stop="openCompany(row)">
                查看字段
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <el-drawer
        v-model="drawerVisible"
        :title="selected?.name || '公司详情'"
        size="72%"
        destroy-on-close
      >
        <template v-if="selected">
          <el-descriptions :column="3" border size="small" class="company-meta">
            <el-descriptions-item label="公司名称">{{ selected.name }}</el-descriptions-item>
            <el-descriptions-item label="产业">{{ industryLabel(selected.industryKey) }}</el-descriptions-item>
            <el-descriptions-item label="队伍">
              {{ selected.teamName || (selected.teamId ? `#${selected.teamId}` : '—') }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">{{ statusLabel(selected.status) }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ selected.createdAt ? formatDateTime(selected.createdAt) : '—' }}
            </el-descriptions-item>
          </el-descriptions>
          <el-tabs v-model="activeTab" class="field-tabs">
            <el-tab-pane label="实体信息表" name="entity">
              <el-empty v-if="!entityGroups.length" description="暂无字段"  :image-size="72" />
              <section v-for="g in entityGroups" :key="g.name" class="field-group">
                <h4 class="group-title">{{ g.name }}</h4>
                <el-table
                  v-loading="tablesLoading"
                  :data="g.fields"
                  stripe
                  size="small"
                 border>
        <template #empty>
          <el-empty description="暂无字段" :image-size="72" />
        </template>
                  <el-table-column label="字段" min-width="200">
                    <template #default="{ row }">
                      <span>{{ row.name }}</span>
                      <span class="field-key">{{ row.key }}</span>
                      <el-tag v-if="row.isCalculated" size="small" type="info" class="formula-tag">
                        公式
                      </el-tag>
                      <el-button
                        link
                        size="small"
                        class="group-btn"
                        @click.stop="openGroupEdit(row)"
                      >
                        分组
                      </el-button>
                    </template>
                  </el-table-column>
                  <el-table-column label="类型" width="90">
                    <template #default="{ row }">{{ typeLabel(row.type) }}</template>
                  </el-table-column>
                  <el-table-column label="值" min-width="220">
                    <template #default="{ row }">
                      <span class="field-value">{{ formatValue(entityValue(row)) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="90" fixed="right">
                    <template #default="{ row }">
                      <el-button v-if="!row.isCalculated" size="small" link type="primary" @click="openEdit(row, null)">
                        修改
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
            </el-tab-pane>
            <el-tab-pane label="财务报表" name="finance">
              <el-alert
                v-if="!fiscalYears.length"
                type="info"
                :closable="false"
                show-icon
                title="本比赛还没有财年数据，财务报表暂无可填写的财年列"
                class="fiscal-hint"
              />
              <el-empty v-if="!financeGroups.length" description="暂无字段"  :image-size="72" />
              <section v-for="g in financeGroups" :key="g.name" class="field-group">
                <h4 class="group-title">{{ g.name }}</h4>
                <el-table
                  v-loading="tablesLoading"
                  :data="g.fields"
                  stripe
                  size="small"
                  class="finance-table"
                 border>
        <template #empty>
          <el-empty description="暂无字段" :image-size="72" />
        </template>
                  <el-table-column label="字段" min-width="190" fixed>
                    <template #default="{ row }">
                      <span>{{ row.name }}</span>
                      <span class="field-key">{{ row.key }}</span>
                      <el-tag v-if="row.isCalculated" size="small" type="info" class="formula-tag">
                        公式
                      </el-tag>
                      <el-button
                        link
                        size="small"
                        class="group-btn"
                        @click.stop="openGroupEdit(row)"
                      >
                        分组
                      </el-button>
                    </template>
                  </el-table-column>
                  <el-table-column label="类型" width="80">
                    <template #default="{ row }">{{ typeLabel(row.type) }}</template>
                  </el-table-column>
                  <el-table-column
                    v-for="fy in fiscalYears"
                    :key="fy.id"
                    :label="`FY${fy.year}`"
                    min-width="140"
                  >
                    <template #default="{ row }">
                      <div class="finance-cell">
                        <span class="field-value">{{ formatValue(financeValue(row, fy.id)) }}</span>
                        <el-button
                          v-if="!row.isCalculated"
                          size="small"
                          link
                          type="primary"
                          @click="openEdit(row, fy.id)"
                        >
                          修改
                        </el-button>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </section>
            </el-tab-pane>
          </el-tabs>
        </template>
      </el-drawer>
      <el-dialog v-model="editVisible" title="修改字段值" width="420px" destroy-on-close>
        <div class="edit-meta">
          <div>
            <b>{{ editField?.name }}</b>
            <span class="field-key">{{ editField?.key }}</span>
          </div>
          <div class="muted">
            {{ editYearId !== null ? `财年：FY${fiscalYearLabel(editYearId)}` : '实体信息表（无财年）' }}
          </div>
        </div>
        <el-form label-width="96px" @submit.prevent>
          <el-form-item label="字段值" required :error="editError">
            <el-input-number
              v-if="editType === 'NUMBER'"
              v-model="editNumber"
              :controls="false"
              class="edit-control"
              placeholder="请输入数值"
            />
            <el-switch v-else-if="editType === 'BOOL'" v-model="editBool" />
            <el-date-picker
              v-else-if="editType === 'DATE'"
              v-model="editDate"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="请选择日期"
              class="edit-control"
            />
            <el-input v-else v-model="editText" class="edit-control" placeholder="请输入字段值" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="submitEdit">保存</el-button>
        </template>
      </el-dialog>
      <el-dialog v-model="groupEditVisible" title="设置字段分组" width="420px" destroy-on-close>
        <div class="edit-meta">
          <div>
            <b>{{ groupEditField?.name }}</b>
            <span class="field-key">{{ groupEditField?.key }}</span>
          </div>
          <div class="muted">分组对本比赛的全部公司生效。</div>
        </div>
        <el-form label-width="96px" @submit.prevent>
          <el-form-item label="分组" required :error="groupError">
            <el-input
              v-model="groupEditText"
              maxlength="40"
              placeholder="如：资产负债、现金流、产能"
              class="edit-control"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="groupEditVisible = false">取消</el-button>
          <el-button type="primary" :loading="groupSaving" @click="submitGroupEdit">保存</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
import type { Company, CompanyField, CompanyTable, FiscalYear, IndustryOption } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'
import { useAuthStore } from '@/stores/auth'
import { useResourceRefresh } from '@/composables/useNotifications'
const props = defineProps<{ cid: string }>()
const auth = useAuthStore()
const isSuperuser = computed(() => auth.isSuperuser)
const companies = ref<Company[]>([])
const industries = ref<IndustryOption[]>([])
const fiscalYears = ref<FiscalYear[]>([])
const keyword = ref('')
const loading = ref(false)
const errorText = ref('')
const filteredCompanies = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return companies.value
  return companies.value.filter(
    (c) =>
      c.name.toLowerCase().includes(kw) ||
      (c.teamName || '').toLowerCase().includes(kw) ||
      (c.industryKey || '').toLowerCase().includes(kw),
  )
})
const selected = ref<Company | null>(null)
const drawerVisible = ref(false)
const activeTab = ref<'entity' | 'finance'>('entity')
const entityTable = ref<CompanyTable | null>(null)
const financeTable = ref<CompanyTable | null>(null)
const tablesLoading = ref(false)
interface FieldGroup {
  name: string
  fields: CompanyField[]
}
/** 按插件给的分组名分块（未分组的归入「其他」） */
function groupFields(fields: CompanyField[] | undefined): FieldGroup[] {
  const map = new Map<string, CompanyField[]>()
  for (const field of fields ?? []) {
    const name = (field.group || '').trim() || '其他'
    const bucket = map.get(name)
    if (bucket) bucket.push(field)
    else map.set(name, [field])
  }
  return [...map.entries()].map(([name, rows]) => ({ name, fields: rows }))
}
const entityGroups = computed(() => groupFields(entityTable.value?.fields))
const financeGroups = computed(() => groupFields(financeTable.value?.fields))
async function load(): Promise<void> {
  if (!isSuperuser.value) return
  loading.value = true
  errorText.value = ''
  try {
    const [companyRows, industryRows, years] = await Promise.all([
      api.getAssignedCompanies(props.cid),
      api.getIndustries(props.cid).catch(() => [] as IndustryOption[]),
      api.getFiscalYears(props.cid).catch(() => [] as FiscalYear[]),
    ])
    companies.value = companyRows
    industries.value = industryRows
    fiscalYears.value = [...years].sort((a, b) => a.year - b.year)
  } catch (err) {
    errorText.value = errorMessage(err, '公司列表加载失败')
  } finally {
    loading.value = false
  }
}
async function loadTables(companyId: number): Promise<void> {
  tablesLoading.value = true
  try {
    const [entity, finance] = await Promise.all([
      api.getCompanyTable(props.cid, companyId, 'entity'),
      api.getCompanyTable(props.cid, companyId, 'finance'),
    ])
    entityTable.value = entity
    financeTable.value = finance
  } catch (err) {
    ElMessage.error(errorMessage(err, '字段值加载失败'))
  } finally {
    tablesLoading.value = false
  }
}
async function openCompany(row: Company): Promise<void> {
  selected.value = row
  drawerVisible.value = true
  activeTab.value = 'entity'
  entityTable.value = null
  financeTable.value = null
  await loadTables(row.id)
}
function industryLabel(key: string): string {
  if (!key) return '—'
  return industries.value.find((i) => i.key === key)?.name || key
}
const STATUS_LABELS: Record<string, string> = {
  ACTIVE: '参赛中',
  WITHDRAWN: '退赛',
  ARCHIVED: '归档',
}
function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status ?? '—'
}
function statusTagType(status: string): 'success' | 'warning' | 'info' {
  if (status === 'ACTIVE') return 'success'
  if (status === 'WITHDRAWN') return 'warning'
  return 'info'
}
const TYPE_LABELS: Record<string, string> = {
  NUMBER: '数值',
  TEXT: '文本',
  BOOL: '布尔',
  DATE: '日期',
  REF: '引用',
}
function typeLabel(type: string): string {
  return TYPE_LABELS[type] ?? type
}
function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
/** 实体信息表字段值：无财年 → JSON 键为 "null" */
function entityValue(field: CompanyField): unknown {
  return field.values?.['null']
}
function financeValue(field: CompanyField, fiscalYearId: number): unknown {
  return field.values?.[String(fiscalYearId)]
}
/** 该字段在该财年行的版本号（实体字段无财年 → 键为 "null"） */
function fieldVersion(field: CompanyField, fiscalYearId: number | null): number | undefined {
  return field.versions?.[fiscalYearId === null ? 'null' : String(fiscalYearId)]
}
function fiscalYearLabel(fiscalYearId: number): string {
  const fy = fiscalYears.value.find((y) => y.id === fiscalYearId)
  return fy ? String(fy.year) : String(fiscalYearId)
}
// ---------- 修改字段值 ----------
const editVisible = ref(false)
const saving = ref(false)
const editField = ref<CompanyField | null>(null)
const editYearId = ref<number | null>(null)
const editType = ref('TEXT')
const editNumber = ref<number | null>(null)
const editBool = ref(false)
const editText = ref('')
const editDate = ref<string | null>(null)
/** 输入框下方的行内错误（Element Plus form-item :error），不用弹窗提示 */
const editError = ref('')
function toNumber(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}
function openEdit(field: CompanyField, fiscalYearId: number | null): void {
  editField.value = field
  editYearId.value = fiscalYearId
  editType.value = field.type
  editError.value = ''
  const raw = fiscalYearId === null ? entityValue(field) : financeValue(field, fiscalYearId)
  editNumber.value = toNumber(raw)
  editBool.value = raw === true || raw === 1 || raw === '1' || raw === 'true'
  editText.value = raw === null || raw === undefined ? '' : String(raw)
  editDate.value = typeof raw === 'string' && raw ? raw : null
  editVisible.value = true
}
/** 输入变化即清除行内错误，重新校验由保存时执行 */
watch([editNumber, editText, editDate, editBool], () => {
  editError.value = ''
})
// ---------- 字段分组 ----------
const groupEditVisible = ref(false)
const groupSaving = ref(false)
const groupEditField = ref<CompanyField | null>(null)
const groupEditText = ref('')
/** 分组名称行内错误（输入框下方） */
const groupError = ref('')
function openGroupEdit(field: CompanyField): void {
  groupEditField.value = field
  groupEditText.value = (field.group || '').trim()
  groupError.value = ''
  groupEditVisible.value = true
}
watch(groupEditText, () => {
  groupError.value = ''
})
async function submitGroupEdit(): Promise<void> {
  const field = groupEditField.value
  const company = selected.value
  if (!field || !company) return
  const group = groupEditText.value.trim()
  if (!group) {
    groupError.value = '请输入分组名称'
    return
  }
  groupSaving.value = true
  try {
    await api.updateIndustryFieldGroup(props.cid, field.key, group)
    ElMessage.success('字段分组已更新')
    groupEditVisible.value = false
    await loadTables(company.id)
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    groupSaving.value = false
  }
}
async function submitEdit(): Promise<void> {
  const field = editField.value
  const company = selected.value
  if (!field || !company) return
  let value: unknown
  if (editType.value === 'NUMBER') {
    if (editNumber.value === null || editNumber.value === undefined) {
      editError.value = '请输入字段值'
      return
    }
    value = editNumber.value
  } else if (editType.value === 'BOOL') {
    value = editBool.value
  } else if (editType.value === 'DATE') {
    if (!editDate.value) {
      editError.value = '请选择日期'
      return
    }
    value = editDate.value
  } else {
    if (!editText.value.trim()) {
      editError.value = '请输入字段值'
      return
    }
    value = editText.value
  }
  saving.value = true
  try {
    await api.updateCompanyField(props.cid, company.id, {
      fieldKey: field.key,
      value,
      fiscalYearId: editYearId.value,
      expectedVersion: fieldVersion(field, editYearId.value),
    })
    ElMessage.success('字段值已更新')
    editVisible.value = false
    await loadTables(company.id)
  } catch (err) {
    ElMessage.error(errorMessage(err, '修改失败'))
  } finally {
    saving.value = false
  }
}
onMounted(load)
useResourceRefresh(['companies', 'teams', 'fiscal-years'], () => {
  void load()
})
</script>
<style scoped lang="scss">
.company-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.page-title {
  margin: 0;
}
.page-head-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.search-input {
  width: 220px;
}
.company-meta {
  margin-bottom: 12px;
}
.field-tabs {
  margin-top: 4px;
}
.field-group {
  margin-bottom: 16px;
}
.field-group:last-child {
  margin-bottom: 0;
}
.group-title {
  margin: 0 0 6px;
  padding-left: 2px;
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
}
.field-key {
  margin-left: 6px;
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}
.formula-tag {
  margin-left: 6px;
}
.group-btn {
  margin-left: 4px;
  font-size: var(--font-xs);
}
.field-value {
  word-break: break-all;
}
.finance-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.fiscal-hint {
  margin-bottom: 8px;
}
.edit-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}
.edit-control {
  width: 100%;
}
.muted {
  color: var(--color-text-tertiary);
}
</style>