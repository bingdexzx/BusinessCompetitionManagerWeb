<script setup lang="ts">
// 结算只算得分与名次，不自动评奖；奖项由超级管理员定义后人工发放/撤销。
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  createAwardGrant,
  createSettlementConfigItem,
  deleteAwardGrant,
  deleteScoringItem,
  getAwardCandidates,
  getAwardGrants,
  getCompanies,
  getSettlementConfig,
  getSettlementResult,
  createJob,
  exportSettlement,
  previewSettlement,
  saveBlob,
  waitJob,
} from '@/api'
import type {
  AwardCandidate,
  AwardDefinition,
  AwardGrant,
  AwardKind,
  Company,
  ScoringConfig,
  ScoringCriterion,
  SettlementConfigPayload,
  SettlementEntry,
  SettlementPreview,
  SettlementResult,
} from '@/api/types'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useCatalog } from '@/composables/useCatalog'
import { useCountUp } from '@/composables/useMotion'
import { formatDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
const props = defineProps<{ cid: string }>()
// 字段键 → 中文名（评分准则里选字段、列表展示都用中文）
const { fieldLabel, fieldOptions } = useCatalog(() => props.cid)
const auth = useAuthStore()
// 仅系统超级管理员/本比赛超级管理员可见、可管理
const canManage = computed(() => auth.isSuperuser)
const canView = canManage
const config = ref<ScoringConfig | null>(null)
const configLoading = ref(false)
const AGG_LABELS: Record<string, string> = {
  SUM: '求和',
  LATEST: '最新值',
  AVERAGE: '平均值',
}
const DIRECTION_LABELS: Record<string, string> = {
  HIGHER_BETTER: '越高越好',
  LOWER_BETTER: '越低越好',
}
async function loadConfig(): Promise<void> {
  configLoading.value = true
  try {
    config.value = await getSettlementConfig(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    configLoading.value = false
  }
}
const dialogVisible = ref(false)
const dialogKind = ref<'criterion' | 'award'>('criterion')
const submitting = ref(false)
const emptyForm = () => ({
  name: '',
  fieldKey: '',
  aggregation: 'SUM' as ScoringCriterion['aggregation'],
  direction: 'HIGHER_BETTER' as ScoringCriterion['direction'],
  weight: 1,
  awardKind: 'INDIVIDUAL' as AwardKind,
  medalLevel: '',
  description: '',
})
const form = reactive(emptyForm())
function openAdd(kind: 'criterion' | 'award'): void {
  dialogKind.value = kind
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}
async function submitAdd(): Promise<void> {
  const name = form.name.trim()
  if (!name) {
    ElMessage.warning(dialogKind.value === 'criterion' ? '请输入准则名称' : '请输入奖项名称')
    return
  }
  if (name.length > 100) {
    ElMessage.warning('名称最长 100 个字符')
    return
  }
  if (dialogKind.value === 'criterion' && !form.fieldKey.trim()) {
    ElMessage.warning('请输入字段键')
    return
  }
  const payload: SettlementConfigPayload =
    dialogKind.value === 'criterion'
      ? {
          kind: 'criterion',
          name,
          fieldKey: form.fieldKey.trim(),
          aggregation: form.aggregation,
          direction: form.direction,
          weight: form.weight,
        }
      : {
          kind: 'award',
          name,
          awardKind: form.awardKind,
          description: form.description.trim() || undefined,
          medalLevel: form.medalLevel.trim() || undefined,
        }
  submitting.value = true
  try {
    await createSettlementConfigItem(props.cid, payload)
    ElMessage.success(dialogKind.value === 'criterion' ? '评分准则已添加' : '奖项已添加')
    dialogVisible.value = false
    await loadConfig()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    submitting.value = false
  }
}
async function removeCriterion(row: ScoringCriterion): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除评分准则「${row.name}」？`, '删除评分准则', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteScoringItem(props.cid, 'criterion', row.id)
    ElMessage.success('评分准则已删除')
    await loadConfig()
  } catch (err) {
    ElMessage.error(errorMessage(err, '删除失败'))
  }
}
async function removeAward(row: AwardDefinition): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除奖项「${row.name}」？该奖项已发放的记录将一并撤销（个人档案中的获奖记录会被回收）。`,
      '删除奖项',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    await deleteScoringItem(props.cid, 'award', row.id)
    ElMessage.success('奖项已删除')
    // 删除奖项会连带撤销发放记录，配置与记录都重拉
    await Promise.all([loadConfig(), loadGrants()])
  } catch (err) {
    ElMessage.error(errorMessage(err, '删除失败'))
  }
}
function kindTagType(kind: AwardKind): 'primary' | 'success' {
  return kind === 'COLLECTIVE' ? 'success' : 'primary'
}
const running = ref(false)
const previewing = ref(false)
const exporting = ref(false)
const previewVisible = ref(false)
const previewData = ref<SettlementPreview | null>(null)
async function openPreview(): Promise<void> {
  previewing.value = true
  try {
    previewData.value = await previewSettlement(props.cid)
    previewVisible.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err, '试算失败'))
  } finally {
    previewing.value = false
  }
}
async function exportReport(): Promise<void> {
  exporting.value = true
  try {
    const blob = await exportSettlement(props.cid)
    saveBlob(blob, '结算报告.xlsx')
    ElMessage.success('结算报告已导出')
  } catch (err) {
    ElMessage.error(errorMessage(err, '导出失败'))
  } finally {
    exporting.value = false
  }
}
const jobProgress = ref(0)
const jobMessage = ref('')
async function startSettlement(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定开始结算？将按当前评分准则计算各公司得分与名次；奖项需在下方「奖项发放」中人工发放。'
      + '\n结算在后台执行，页面会显示进度。',
      '开始结算',
      {
        type: 'warning',
        confirmButtonText: '开始结算',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  running.value = true
  jobProgress.value = 0
  jobMessage.value = '已提交后台任务'
  try {
    const job = await createJob(props.cid, 'SETTLEMENT')
    const finalJob = await waitJob(props.cid, job.id, (current) => {
      jobProgress.value = current.progress
      jobMessage.value = current.message || current.statusLabel
    })
    if (finalJob.status === 'FAILED') {
      ElMessage.error(finalJob.error || '结算失败')
      return
    }
    ElMessage.success('结算已完成')
    await loadResult()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    running.value = false
    jobMessage.value = ''
    jobProgress.value = 0
  }
}
const result = ref<SettlementResult | null>(null)
const resultLoading = ref(false)
async function loadResult(): Promise<void> {
  resultLoading.value = true
  try {
    result.value = await getSettlementResult(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    resultLoading.value = false
  }
}
function detailRows(row: SettlementEntry): Array<{
  key: string
  value: number
  normalized: number
  weight: number
  score: number
}> {
  return Object.entries(row.detail ?? {}).map(([key, d]) => ({ key, ...d }))
}
function fmtScore(value: number | null | undefined): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(2) : '—'
}
function isTopRank(rank: number): boolean {
  return Number.isFinite(rank) && rank >= 1 && rank <= 3
}
const resultEntries = computed(() => result.value?.entries ?? [])
const topScore = computed(() =>
  resultEntries.value.reduce((max, e) => Math.max(max, Number(e.score) || 0), 0),
)
const avgScore = computed(() => {
  const list = resultEntries.value
  if (!list.length) return 0
  return list.reduce((sum, e) => sum + (Number(e.score) || 0), 0) / list.length
})
const topScoreShown = useCountUp(topScore, { precision: 2 })
const avgScoreShown = useCountUp(avgScore, { precision: 2 })
const entryCountShown = useCountUp(computed(() => resultEntries.value.length), { precision: 0 })
const awardOptions = computed<AwardDefinition[]>(() => config.value?.awards ?? [])
const grantForm = reactive({
  awardId: null as number | null,
  userId: null as number | null,
  companyId: null as number | null,
  note: '',
})
const granting = ref(false)
const selectedAward = computed<AwardDefinition | null>(
  () => awardOptions.value.find((a) => a.id === grantForm.awardId) ?? null,
)
const isIndividual = computed(() => selectedAward.value?.kind === 'INDIVIDUAL')
const isCollective = computed(() => selectedAward.value?.kind === 'COLLECTIVE')
const candidates = ref<AwardCandidate[]>([])
const candidatesLoading = ref(false)
async function searchCandidates(q: string): Promise<void> {
  candidatesLoading.value = true
  try {
    const picked = candidates.value.find((c) => c.userId === grantForm.userId)
    const list = await getAwardCandidates(props.cid, q.trim() || undefined)
    // 保留已选人员，避免搜索后回退显示用户 ID
    if (picked && !list.some((c) => c.userId === picked.userId)) list.unshift(picked)
    candidates.value = list
  } catch (err) {
    ElMessage.error(errorMessage(err, '候选人加载失败'))
  } finally {
    candidatesLoading.value = false
  }
}
const companies = ref<Company[]>([])
const companiesLoading = ref(false)
async function loadCompanies(): Promise<void> {
  companiesLoading.value = true
  try {
    companies.value = await getCompanies(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '公司列表加载失败'))
  } finally {
    companiesLoading.value = false
  }
}
function onAwardChange(): void {
  grantForm.userId = null
  grantForm.companyId = null
  if (isIndividual.value) {
    void searchCandidates('')
  }
}
function resetGrantForm(): void {
  grantForm.awardId = null
  grantForm.userId = null
  grantForm.companyId = null
  grantForm.note = ''
}
async function submitGrant(): Promise<void> {
  const award = selectedAward.value
  if (!award) {
    ElMessage.warning('请先选择奖项')
    return
  }
  const note = grantForm.note.trim()
  if (award.kind === 'INDIVIDUAL') {
    const userId = grantForm.userId
    if (!userId) {
      ElMessage.warning('请选择获奖人')
      return
    }
    const person = candidates.value.find((c) => c.userId === userId)
    const who = person ? person.displayName || person.username : `用户 #${userId}`
    try {
      await ElMessageBox.confirm(`确定为「${who}」发放奖项「${award.name}」？`, '发放奖项', {
        type: 'warning',
        confirmButtonText: '发放',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    granting.value = true
    try {
      const res = await createAwardGrant(props.cid, { awardId: award.id, userId })
      ElMessage.success(`奖项已发放，共写入 ${res.recipientCount} 人的档案记录`)
      resetGrantForm()
      await loadGrants()
    } catch (err) {
      ElMessage.error(errorMessage(err, '发放失败'))
    } finally {
      granting.value = false
    }
    return
  }
  const companyId = grantForm.companyId
  if (!companyId) {
    ElMessage.warning('请选择获奖公司')
    return
  }
  const companyName = companies.value.find((c) => c.id === companyId)?.name ?? `公司 #${companyId}`
  try {
    await ElMessageBox.confirm(
      `确定向公司「${companyName}」发放奖项「${award.name}」？该奖项将记录到该公司队伍全部成员的个人档案（受益人数以发放结果为准）。`,
      '发放奖项',
      {
        type: 'warning',
        confirmButtonText: '发放',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  granting.value = true
  try {
    const res = await createAwardGrant(props.cid, {
      awardId: award.id,
      companyId,
      note: note || undefined,
    })
    ElMessage.success(`奖项已发放，共写入 ${res.recipientCount} 人的档案记录`)
    resetGrantForm()
    await loadGrants()
  } catch (err) {
    ElMessage.error(errorMessage(err, '发放失败'))
  } finally {
    granting.value = false
  }
}
const grants = ref<AwardGrant[]>([])
const grantsLoading = ref(false)
async function loadGrants(): Promise<void> {
  grantsLoading.value = true
  try {
    grants.value = await getAwardGrants(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '发放记录加载失败'))
  } finally {
    grantsLoading.value = false
  }
}
function grantTargetLabel(row: AwardGrant): string {
  if (row.kind === 'INDIVIDUAL') return row.userName || '—'
  return `${row.companyName || '—'}（${row.recipientCount} 人）`
}
async function revokeGrant(row: AwardGrant): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定撤销奖项「${row.awardName}」对 ${grantTargetLabel(row)} 的发放？对应的个人档案获奖记录会一并删除。`,
      '撤销发放',
      {
        type: 'warning',
        confirmButtonText: '撤销',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  try {
    const res = await deleteAwardGrant(props.cid, row.id)
    ElMessage.success(`奖项发放已撤销，回收 ${res.removed} 条档案记录`)
    await loadGrants()
  } catch (err) {
    ElMessage.error(errorMessage(err, '撤销失败'))
  }
}
async function reloadAll(): Promise<void> {
  await Promise.all([loadConfig(), loadResult(), loadGrants(), loadCompanies()])
}
// 结算/奖项/公司变更后 400ms 去抖重拉，仍只超级管理员加载
useResourceRefresh(['settlement', 'awards', 'companies'], () => {
  if (canView.value) void reloadAll()
})
onMounted(() => {
  if (canView.value) void reloadAll()
})
</script>
<template>
  <div class="settlement-page anim-stagger page">
    <PageHeader title="结算管理" />
    <!-- 结算结果仅超级管理员可见 -->
    <el-empty v-if="!canView" description="结算与获奖仅超级管理员可见"  :image-size="72" />
    <template v-if="canView">
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="section-title">评分准则</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="loadConfig">刷新</el-button>
            <el-button v-if="canManage" type="primary" :icon="Plus" @click="openAdd('criterion')">
              新建准则
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="config?.criteria ?? []" v-loading="configLoading" stripe size="small" border class="table--sticky-head" max-height="calc(100vh - 360px)">
        <el-table-column prop="name" label="准则名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="评分字段" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ fieldLabel(row.fieldKey) }}</template>
        </el-table-column>
        <el-table-column label="聚合方式" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ AGG_LABELS[row.aggregation] ?? row.aggregation }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="方向" width="110">
          <template #default="{ row }">
            {{ DIRECTION_LABELS[row.direction] ?? row.direction }}
          </template>
        </el-table-column>
        <el-table-column label="权重" width="90" align="right">
          <template #default="{ row }">
            <span class="value-num">{{ row.weight }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" link size="small" class="danger-op" @click="removeCriterion(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>暂无评分准则</template>
      </el-table>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="section-title">奖项设置</span>
          <div class="card-actions">
            <el-button v-if="canManage" type="primary" :icon="Plus" @click="openAdd('award')">
              新建奖项
            </el-button>
          </div>
        </div>
      </template>
      <el-table :data="config?.awards ?? []" v-loading="configLoading" stripe size="small" border>
        <el-table-column prop="name" label="奖项名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="kindTagType(row.kind)">
              {{ row.kindLabel || (row.kind === 'COLLECTIVE' ? '集体奖' : '个人奖') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="奖牌等级" min-width="120">
          <template #default="{ row }">
            <span v-if="row.medalLevel">{{ row.medalLevel }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.description">{{ row.description }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" link size="small" class="danger-op" @click="removeAward(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>暂无奖项，请先「新建奖项」</template>
      </el-table>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="section-title">结算结果</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="loadResult">刷新</el-button>
            <el-button
              v-if="canManage"
              :loading="previewing"
              :disabled="previewing || running"
              @click="openPreview"
            >
              试算
            </el-button>
            <el-button :loading="exporting" :disabled="exporting" @click="exportReport">
              导出报告
            </el-button>
            <el-button
              v-if="canManage"
              type="primary"
              :loading="running"
              :disabled="running"
              @click="startSettlement"
            >
              开始结算
            </el-button>
            <span v-if="running" class="job-progress">
              <el-progress
                :percentage="jobProgress"
                :stroke-width="6"
                :show-text="false"
                class="job-progress-bar"
              />
              <span class="job-progress-text">{{ jobMessage }}</span>
            </span>
          </div>
        </div>
      </template>
      <div v-loading="resultLoading">
        <div v-if="resultLoading && !result" class="result-skeleton">
          <div v-for="i in 3" :key="i" class="skeleton skeleton-card" />
        </div>
        <template v-else-if="result?.run">
          <div class="run-summary">
            <el-tag type="success" effect="plain">最近结算</el-tag>
            <span class="run-meta">
              结算时间：{{ formatDateTime(result.run.createdAt) }}，共
              {{ result.entries.length }} 条名次记录
            </span>
          </div>
          <div class="metric-grid result-metrics anim-stagger">
            <div class="metric-card">
              <span class="metric-label">参评公司</span>
              <div class="metric-value">
                {{ entryCountShown }}<span class="metric-unit">家</span>
              </div>
            </div>
            <div class="metric-card">
              <span class="metric-label">最高得分</span>
              <div class="metric-value">{{ topScoreShown.toFixed(2) }}</div>
            </div>
            <div class="metric-card">
              <span class="metric-label">平均得分</span>
              <div class="metric-value">{{ avgScoreShown.toFixed(2) }}</div>
            </div>
          </div>
          <el-table :data="result.entries" stripe size="small" border>
            <el-table-column label="名次" width="90" align="center">
              <template #default="{ row }">
                <span class="rank-badge value-num" :class="{ 'is-top': isTopRank(row.rank) }">
                  {{ row.rank }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="companyName" label="公司" min-width="160" show-overflow-tooltip />
            <el-table-column label="得分" width="120" align="right">
              <template #default="{ row }">
                <span class="score-cell value-num">{{ fmtScore(row.score) }}</span>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="detail-wrap">
                  <el-table :data="detailRows(row)" size="small" border>
                    <el-table-column prop="key" label="指标" min-width="150" show-overflow-tooltip />
                    <el-table-column label="原始值" width="120" align="right">
                      <template #default="{ row: d }">
                        <span class="value-num">{{ fmtScore(d.value) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="归一化" width="120" align="right">
                      <template #default="{ row: d }">
                        <span class="value-num">{{ fmtScore(d.normalized) }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="权重" width="100" align="right">
                      <template #default="{ row: d }">
                        <span class="value-num">{{ d.weight }}</span>
                      </template>
                    </el-table-column>
                    <el-table-column label="得分" width="120" align="right">
                      <template #default="{ row: d }">
                        <span class="value-num">{{ fmtScore(d.score) }}</span>
                      </template>
                    </el-table-column>
                    <template #empty>暂无逐准则明细</template>
                  </el-table>
                </div>
              </template>
            </el-table-column>
            <template #empty>暂无名次记录</template>
          </el-table>
        </template>
        <el-empty v-else description="尚未执行结算"  :image-size="72" />
      </div>
    </el-card>
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="section-title">奖项发放</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="loadGrants">刷新</el-button>
          </div>
        </div>
      </template>
      <template v-if="canManage">
        <el-alert
          v-if="awardOptions.length === 0"
          type="info"
          :closable="false"
          show-icon
          title="请先在上方「奖项设置」中新建奖项，再进行发放。"
          class="hint-alert"
        />
        <div v-else class="grant-form">
          <div class="grant-field">
            <span class="grant-label">选择奖项</span>
            <el-select
              v-model="grantForm.awardId"
              placeholder="请选择奖项"
              clearable
              style="width: 220px"
              @change="onAwardChange"
            >
              <el-option
                v-for="a in awardOptions"
                :key="a.id"
                :label="`${a.name}（${a.kindLabel || (a.kind === 'COLLECTIVE' ? '集体奖' : '个人奖')}）`"
                :value="a.id"
              />
            </el-select>
          </div>
          <div v-if="isIndividual" class="grant-field">
            <span class="grant-label">获奖人</span>
            <el-select
              v-model="grantForm.userId"
              filterable
              remote
              clearable
              reserve-keyword
              :remote-method="searchCandidates"
              :loading="candidatesLoading"
              no-data-text="输入姓名或用户名搜索本比赛成员"
              placeholder="搜索本比赛成员"
              style="width: 260px"
            >
              <el-option
                v-for="c in candidates"
                :key="c.userId"
                :label="c.displayName || c.username"
                :value="c.userId"
              >
                <span>{{ c.displayName || c.username }}</span>
                <span v-if="c.companyName" class="option-sub">{{ c.companyName }}</span>
              </el-option>
            </el-select>
          </div>
          <div v-else-if="isCollective" class="grant-field">
            <span class="grant-label">获奖公司</span>
            <el-select
              v-model="grantForm.companyId"
              filterable
              clearable
              :loading="companiesLoading"
              placeholder="请选择公司（发放给其队伍全员）"
              style="width: 260px"
            >
              <el-option v-for="c in companies" :key="c.id" :label="c.name" :value="c.id" />
            </el-select>
          </div>
          <div class="grant-field">
            <span class="grant-label">可选备注</span>
            <el-input
              v-model="grantForm.note"
              maxlength="200"
              placeholder="备注（可选）"
              style="width: 220px"
            />
          </div>
          <el-button type="primary" :loading="granting" :disabled="granting" @click="submitGrant">
            发放
          </el-button>
        </div>
      </template>
      <el-table :data="grants" v-loading="grantsLoading" stripe class="grant-table" size="small" border>
        <el-table-column prop="awardName" label="奖项" min-width="140" show-overflow-tooltip />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="kindTagType(row.kind)">
              {{ row.kindLabel || (row.kind === 'COLLECTIVE' ? '集体奖' : '个人奖') }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发放对象" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.kind === 'INDIVIDUAL'">{{ row.userName || '—' }}</span>
            <span v-else>{{ row.companyName || '—' }}（{{ row.recipientCount }} 人）</span>
          </template>
        </el-table-column>
        <el-table-column label="奖牌等级" width="110">
          <template #default="{ row }">
            <span v-if="row.medalLevel">{{ row.medalLevel }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.note">{{ row.note }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="发放人" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.grantedByUsername || '—' }}</template>
        </el-table-column>
        <el-table-column label="发放时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.grantedAt) }}</template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" link size="small" class="danger-op" @click="revokeGrant(row)">
              撤销
            </el-button>
          </template>
        </el-table-column>
        <template #empty>暂无发放记录</template>
      </el-table>
    </el-card>
    <el-dialog
      v-model="dialogVisible"
      :title="dialogKind === 'criterion' ? '新增评分准则' : '新建奖项'"
      width="560px"
    >
      <el-form label-width="96px">
        <template v-if="dialogKind === 'criterion'">
          <el-form-item label="准则名称" required>
            <el-input v-model="form.name" placeholder="如：净利润" maxlength="64" />
          </el-form-item>
          <el-form-item label="评分字段" required>
            <el-select
              v-model="form.fieldKey"
              filterable
              allow-create
              default-first-option
              placeholder="选择产业字段（可搜索中文名）"
              style="width: 100%"
            >
              <el-option
                v-for="opt in fieldOptions"
                :key="opt.value"
                :label="opt.label"
                :value="opt.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="聚合方式">
            <el-select v-model="form.aggregation" style="width: 100%">
              <el-option label="求和（SUM）" value="SUM" />
              <el-option label="最新值（LATEST）" value="LATEST" />
              <el-option label="平均值（AVERAGE）" value="AVERAGE" />
            </el-select>
          </el-form-item>
          <el-form-item label="方向">
            <el-select v-model="form.direction" style="width: 100%">
              <el-option label="越高越好" value="HIGHER_BETTER" />
              <el-option label="越低越好" value="LOWER_BETTER" />
            </el-select>
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="form.weight" :min="0" :step="0.1" style="width: 100%" />
          </el-form-item>
        </template>
        <template v-else>
          <el-form-item label="名称" required>
            <el-input v-model="form.name" placeholder="如：最佳 CEO" maxlength="100" />
          </el-form-item>
          <el-form-item label="类型" required>
            <el-select v-model="form.awardKind" style="width: 100%">
              <el-option label="个人奖（发放给 1 人）" value="INDIVIDUAL" />
              <el-option label="集体奖（发放给公司队伍全员）" value="COLLECTIVE" />
            </el-select>
          </el-form-item>
          <el-form-item label="奖牌等级">
            <el-input v-model="form.medalLevel" placeholder="可选，如：一等奖 / GOLD" maxlength="32" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input
              v-model="form.description"
              type="textarea"
              :rows="3"
              maxlength="200"
              show-word-limit
              placeholder="可选，如评选标准"
            />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">确定</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="previewVisible" title="结算试算（不会保存）" width="720px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="试算只按当前评分准则计算得分与名次，不写入结算记录；确认无误后再点「开始结算」。"
        class="preview-hint"
      />
      <el-table :data="previewData?.entries ?? []" border size="small" stripe>
        <el-table-column prop="rank" label="名次" width="70" align="center" />
        <el-table-column prop="companyName" label="公司" min-width="140" />
        <el-table-column label="指标得分" min-width="240">
          <template #default="{ row }">
            <span v-for="(item, name) in row.detail" :key="name" class="preview-score">
              {{ name }}：{{ item.score }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="总分" width="90" align="right">
          <template #default="{ row }">
            <b class="value-num">{{ row.score }}</b>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
    </template>
  </div>
</template>
<style scoped>
.job-progress {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
}
.job-progress-bar {
  width: 90px;
}
.job-progress-text {
  color: var(--color-text-tertiary);
  font-size: 12px;
}
.preview-hint {
  margin-bottom: 12px;
}
.preview-score {
  margin-right: 12px;
  color: var(--color-text-secondary);
  font-size: 12px;
}
.settlement-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.hint-alert {
  margin-bottom: 0;
}
.section-card {
  margin: 0;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.card-head .section-title {
  margin-bottom: 0;
}
.card-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.result-metrics {
  margin-bottom: 16px;
}
.result-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.rank-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 26px;
  height: 22px;
  padding: 0 8px;
  border-radius: var(--radius-full);
  font-weight: 600;
  color: var(--color-text-secondary);
  background: var(--surface-sunken);
}
.rank-badge.is-top {
  color: var(--color-primary);
  background: rgba(var(--color-primary-rgb), 0.12);
}
.score-cell {
  font-weight: 600;
  color: var(--color-text-primary);
}
/* 危险操作默认弱化，悬停才显红 */
.section-card :deep(.danger-op) {
  color: var(--color-text-tertiary);
}
.section-card :deep(.danger-op:hover) {
  color: var(--color-danger);
}
.run-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.run-meta {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
}
.detail-wrap {
  padding: 8px 16px 12px;
}
.muted {
  color: var(--color-text-tertiary);
}
.grant-form {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.grant-field {
  display: flex;
  align-items: center;
  gap: 8px;
}
.grant-label {
  color: var(--color-text-secondary);
  font-size: var(--font-sm);
  white-space: nowrap;
}
.option-sub {
  float: right;
  margin-left: 12px;
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}
.grant-table {
  margin-top: 4px;
}
</style>