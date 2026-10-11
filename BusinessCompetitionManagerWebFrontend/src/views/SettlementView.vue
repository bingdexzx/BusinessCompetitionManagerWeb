<script setup lang="ts">
// 结算管理：评分准则 / 获奖规则配置 + 结算执行与结果展示
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  createScoringItem,
  deleteScoringItem,
  getScoringConfig,
  getSettlementResult,
  runSettlement,
} from '@/api'
import type {
  AwardRule,
  ScoringConfig,
  ScoringCriterion,
  SettlementEntry,
  SettlementResult,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ cid: string }>()
const auth = useAuthStore()

/** 系统超管 / 本比赛超管可维护配置与执行结算 */
const canManage = computed(() => {
  if (auth.isSuperuser) return true
  return auth.memberships.some((m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN')
})

// ---------- 评分配置 ----------
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
    config.value = await getScoringConfig(props.cid)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    configLoading.value = false
  }
}

// ---------- 新增对话框（准则 / 获奖规则共用） ----------
const dialogVisible = ref(false)
const dialogKind = ref<'criterion' | 'award'>('criterion')
const submitting = ref(false)

const emptyForm = () => ({
  name: '',
  fieldKey: '',
  aggregation: 'SUM' as 'SUM' | 'LATEST' | 'AVERAGE',
  direction: 'HIGHER_BETTER' as 'HIGHER_BETTER' | 'LOWER_BETTER',
  weight: 1,
  awardLevel: '',
  rankFrom: 1,
  rankTo: 1,
  medalLevel: '',
})
const form = reactive(emptyForm())

function openAdd(kind: 'criterion' | 'award'): void {
  dialogKind.value = kind
  Object.assign(form, emptyForm())
  dialogVisible.value = true
}

async function submitAdd(): Promise<void> {
  // 简单必填校验
  if (dialogKind.value === 'criterion') {
    if (!form.name.trim() || !form.fieldKey.trim()) {
      ElMessage.warning('请填写准则名称与字段键')
      return
    }
  } else {
    if (!form.awardLevel.trim() || !form.medalLevel.trim()) {
      ElMessage.warning('请填写奖项等级与奖牌等级')
      return
    }
    if (form.rankFrom < 1 || form.rankTo < form.rankFrom) {
      ElMessage.warning('名次区间不合法（起始名次 ≥ 1，结束 ≥ 起始）')
      return
    }
  }

  submitting.value = true
  try {
    const payload =
      dialogKind.value === 'criterion'
        ? {
            kind: 'criterion' as const,
            name: form.name.trim(),
            fieldKey: form.fieldKey.trim(),
            aggregation: form.aggregation,
            direction: form.direction,
            weight: form.weight,
          }
        : {
            kind: 'award' as const,
            awardLevel: form.awardLevel.trim(),
            rankFrom: form.rankFrom,
            rankTo: form.rankTo,
            medalLevel: form.medalLevel.trim(),
          }
    await createScoringItem(props.cid, payload)
    ElMessage.success('已添加')
    dialogVisible.value = false
    await loadConfig()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    submitting.value = false
  }
}

async function removeCriterion(row: ScoringCriterion): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除评分准则「${row.name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteScoringItem(props.cid, 'criterion', row.id)
    ElMessage.success('已删除')
    await loadConfig()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  }
}

async function removeAwardRule(row: AwardRule): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认删除获奖规则「${row.awardLevel}」？`, '删除确认', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await deleteScoringItem(props.cid, 'award', row.id)
    ElMessage.success('已删除')
    await loadConfig()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  }
}

// ---------- 结算执行 ----------
const running = ref(false)

async function startSettlement(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确认开始结算？将按当前评分准则计算各公司得分、名次与获奖。',
      '开始结算',
      { type: 'warning' },
    )
  } catch {
    return
  }
  running.value = true
  try {
    await runSettlement(props.cid)
    ElMessage.success('结算完成')
    await loadResult()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    running.value = false
  }
}

// ---------- 结算结果 ----------
const result = ref<SettlementResult | null>(null)
const resultLoading = ref(false)

async function loadResult(): Promise<void> {
  resultLoading.value = true
  try {
    result.value = await getSettlementResult(props.cid)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '操作失败')
  } finally {
    resultLoading.value = false
  }
}

/** 获奖等级标签配色 */
function awardTagType(level: string): 'danger' | 'warning' | 'success' | 'info' {
  if (level.includes('一') || level.toUpperCase().includes('GOLD')) return 'danger'
  if (level.includes('二') || level.toUpperCase().includes('SILVER')) return 'warning'
  if (level.includes('三') || level.toUpperCase().includes('BRONZE')) return 'success'
  return 'info'
}

/** 展开行：逐准则得分明细 */
function detailRows(row: SettlementEntry): Array<{
  key: string
  value: number
  normalized: number
  weight: number
  score: number
}> {
  return Object.entries(row.detail ?? {}).map(([key, d]) => ({ key, ...d }))
}

async function reloadAll(): Promise<void> {
  await Promise.all([loadConfig(), loadResult()])
}

onMounted(() => void reloadAll())
</script>

<template>
  <div class="settlement-page">
    <h1 class="page-title">结算管理</h1>

    <el-alert
      class="hint-alert"
      type="info"
      :closable="false"
      show-icon
      title="评分准则为可配置框架（决策 D11），细则待需求方提供后调整。"
    />

    <!-- ===== 评分准则 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">评分准则</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="loadConfig">刷新</el-button>
            <el-button v-if="canManage" type="primary" :icon="Plus" @click="openAdd('criterion')">
              新增准则
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="config?.criteria ?? []" v-loading="configLoading" stripe>
        <el-table-column prop="name" label="准则名称" min-width="150" show-overflow-tooltip />
        <el-table-column prop="fieldKey" label="字段键" min-width="140" show-overflow-tooltip />
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
        <el-table-column prop="weight" label="权重" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" text size="small" @click="removeCriterion(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无评分准则</template>
      </el-table>
    </el-card>

    <!-- ===== 获奖规则 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">获奖规则</span>
          <div class="card-actions">
            <el-button v-if="canManage" type="primary" :icon="Plus" @click="openAdd('award')">
              新增规则
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="config?.awardRules ?? []" v-loading="configLoading" stripe>
        <el-table-column prop="awardLevel" label="奖项等级" min-width="140" />
        <el-table-column label="名次区间" width="130">
          <template #default="{ row }"> 第 {{ row.rankFrom }} - {{ row.rankTo }} 名 </template>
        </el-table-column>
        <el-table-column prop="medalLevel" label="奖牌等级" min-width="120" />
        <el-table-column v-if="canManage" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" text size="small" @click="removeAwardRule(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无获奖规则</template>
      </el-table>
    </el-card>

    <!-- ===== 开始结算 + 结果 ===== -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <span class="card-title">结算结果</span>
          <div class="card-actions">
            <el-button :icon="Refresh" @click="loadResult">刷新</el-button>
            <el-button
              v-if="canManage"
              type="primary"
              :loading="running"
              :disabled="running"
              @click="startSettlement"
            >
              开始结算
            </el-button>
          </div>
        </div>
      </template>

      <div v-loading="resultLoading">
        <template v-if="result?.run">
          <div class="run-summary">
            <el-tag type="success" effect="plain">最近结算</el-tag>
            <span class="run-meta">
              结算时间：{{ formatDateTime(result.run.createdAt) }}，共
              {{ result.entries.length }} 条名次记录
            </span>
          </div>

          <el-table :data="result.entries" stripe>
            <el-table-column prop="rank" label="名次" width="80" />
            <el-table-column prop="companyName" label="公司" min-width="160" show-overflow-tooltip />
            <el-table-column prop="score" label="得分" width="110" />
            <el-table-column label="获奖等级" width="130">
              <template #default="{ row }">
                <el-tag v-if="row.awardLevel" :type="awardTagType(row.awardLevel)" size="small">
                  {{ row.awardLevel }}
                </el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="detail-wrap">
                  <el-table :data="detailRows(row)" size="small" border>
                    <el-table-column prop="key" label="指标" min-width="150" show-overflow-tooltip />
                    <el-table-column prop="value" label="原始值" width="120" />
                    <el-table-column prop="normalized" label="归一化" width="120" />
                    <el-table-column prop="weight" label="权重" width="100" />
                    <el-table-column prop="score" label="得分" width="120" />
                    <template #empty>暂无逐准则明细</template>
                  </el-table>
                </div>
              </template>
            </el-table-column>
            <template #empty>暂无名次记录</template>
          </el-table>
        </template>
        <el-empty v-else description="尚未执行结算" />
      </div>
    </el-card>

    <!-- ===== 新增对话框 ===== -->
    <el-dialog
      v-model="dialogVisible"
      :title="dialogKind === 'criterion' ? '新增评分准则' : '新增获奖规则'"
      width="min(520px, 92vw)"
    >
      <el-form label-width="96px">
        <template v-if="dialogKind === 'criterion'">
          <el-form-item label="准则名称" required>
            <el-input v-model="form.name" placeholder="如：净利润" maxlength="64" />
          </el-form-item>
          <el-form-item label="字段键" required>
            <el-input v-model="form.fieldKey" placeholder="如：netProfit" maxlength="64" />
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
          <el-form-item label="奖项等级" required>
            <el-input v-model="form.awardLevel" placeholder="如：一等奖" maxlength="32" />
          </el-form-item>
          <el-form-item label="名次区间">
            <div class="rank-range">
              <el-input-number v-model="form.rankFrom" :min="1" :step="1" />
              <span class="rank-sep">至</span>
              <el-input-number v-model="form.rankTo" :min="1" :step="1" />
            </div>
          </el-form-item>
          <el-form-item label="奖牌等级" required>
            <el-input v-model="form.medalLevel" placeholder="如：GOLD" maxlength="32" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdd">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
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
.card-title {
  font-weight: 600;
}
.card-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
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
.rank-range {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.rank-sep {
  color: var(--color-text-secondary);
}
</style>
