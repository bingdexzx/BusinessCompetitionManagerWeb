<script setup lang="ts">
// 系统设置 — 流量限制（仅系统超级管理员）：登录限流 + API 每分钟限流 + 限流记录清理
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useCountUp } from '@/composables/useMotion'
import {
  clearRateLimitRecords,
  getRateLimit,
  resetRateLimit,
  saveRateLimit,
  type ApiPerMinuteLimits,
  type RateLimitConfig,
  type RateLimitStats,
} from '@/api/settingsApi'
import { errorMessage } from '@/utils/errors'
import { useResourceRefresh } from '@/composables/useNotifications'
/** 五角色固定键集合 + 中文名（与后端 api.perMinute 严格一致） */
interface RoleRow {
  key: keyof ApiPerMinuteLimits
  label: string
  desc: string
}
const roleRows: RoleRow[] = [
  { key: 'superuser', label: '超级管理员', desc: '系统级管理账号' },
  { key: 'admin', label: '管理员（主席团）', desc: '比赛内管理员' },
  { key: 'player', label: '参赛代表', desc: '参赛队伍成员' },
  { key: 'anonymous', label: '匿名 / 无身份', desc: '未登录或无比赛身份的用户' },
]
// el-table 插槽的 row 是 any，这里用带类型的读写器避免隐式 any 索引
function perMinuteOf(row: RoleRow): number {
  return form.value.api.perMinute[row.key]
}
function setPerMinute(row: RoleRow, value: number | undefined): void {
  form.value.api.perMinute[row.key] = Math.round(Number(value ?? 1))
}
function defaultConfig(): RateLimitConfig {
  return {
    login: { failLimit: 10, windowSeconds: 300, lockSeconds: 900 },
    api: {
      enabled: true,
      perMinute: {
        superuser: 600,
        admin: 200,
        player: 120,
        anonymous: 30,
      },
    },
  }
}
const loading = ref(false)
const saving = ref(false)
const resetting = ref(false)
const clearing = ref(false)
const form = ref<RateLimitConfig>(defaultConfig())
/** 锁定时长按「分钟」编辑，保存时换算成秒（后端存 lockSeconds） */
const lockMinutes = ref(15)
const stats = ref<RateLimitStats>({ throttleRecords: 0, activeLocks: 0 })
// 统计数字：随实时刷新平滑滚动（useCountUp 首次赋值不播动画）
const throttleShown = useCountUp(computed(() => stats.value.throttleRecords))
const activeLocksShown = useCountUp(computed(() => stats.value.activeLocks))
function applyConfig(config: RateLimitConfig): void {
  form.value = {
    login: { ...config.login },
    api: {
      enabled: config.api.enabled,
      perMinute: { ...config.api.perMinute },
    },
  }
  lockMinutes.value = Math.max(1, Math.round(config.login.lockSeconds / 60))
}
async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await getRateLimit()
    applyConfig(res.config)
    stats.value = res.stats
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    loading.value = false
  }
}
// 实时刷新：系统设置（/api/system/rate-limit → 资源名 system）变更广播后重拉配置与统计
useResourceRefresh(['system'], load)
/** 本地数值必须为正整数（后端严格校验，这里先给出友好拦截） */
function buildPayload(): RateLimitConfig | null {
  const failLimit = Math.round(Number(form.value.login.failLimit))
  const windowSeconds = Math.round(Number(form.value.login.windowSeconds))
  const lockSeconds = Math.round(Number(lockMinutes.value)) * 60
  const perMinute = {} as ApiPerMinuteLimits
  for (const { key } of roleRows) {
    perMinute[key] = Math.round(Number(form.value.api.perMinute[key]))
  }
  const values = [failLimit, windowSeconds, lockSeconds, ...Object.values(perMinute)]
  if (values.some((v) => !Number.isFinite(v) || v < 1)) return null
  return {
    login: { failLimit, windowSeconds, lockSeconds },
    api: { enabled: form.value.api.enabled, perMinute },
  }
}
async function save(): Promise<void> {
  const payload = buildPayload()
  if (!payload) {
    ElMessage.warning('限流数值必须是正整数，请检查后重试')
    return
  }
  saving.value = true
  try {
    applyConfig(await saveRateLimit(payload))
    ElMessage.success('限流设置已保存')
    await refreshStats()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    saving.value = false
  }
}
async function reset(): Promise<void> {
  resetting.value = true
  try {
    applyConfig(await resetRateLimit())
    ElMessage.success('限流配置已恢复默认')
    await refreshStats()
  } catch (err) {
    ElMessage.error(errorMessage(err, '恢复默认失败'))
  } finally {
    resetting.value = false
  }
}
async function refreshStats(): Promise<void> {
  try {
    stats.value = (await getRateLimit()).stats
  } catch {
    // 统计刷新失败不打扰用户，主操作已完成
  }
}
async function clearRecords(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定清空全部限流记录？包含 API 请求计数与登录失败限流记录，清空后相关限制立即重新计算。',
      '清空限流记录',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  clearing.value = true
  try {
    const res = await clearRateLimitRecords()
    ElMessage.success(`限流记录已清空 ${res.cleared} 条`)
    await refreshStats()
  } catch (err) {
    ElMessage.error(errorMessage(err, '清空失败'))
  } finally {
    clearing.value = false
  }
}
onMounted(() => void load())
</script>
<template>
  <div class="settings-view page">
    <div class="page-toolbar">
      <PageHeader title="系统设置">
        <template #actions>
          <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
        </template>
      </PageHeader>
    </div>
    <!-- ===== 限流概况 ===== -->
    <section class="panel settings-panel anim-fade-in-up">
      <h2 class="section-title">限流概况</h2>
      <div class="metric-grid">
        <div class="metric-card">
          <div class="metric-label">当前计数记录数</div>
          <div class="metric-value">{{ throttleShown }}<span class="metric-unit">条</span></div>
        </div>
        <div class="metric-card">
          <div class="metric-label">生效锁数</div>
          <div class="metric-value">{{ activeLocksShown }}<span class="metric-unit">个</span></div>
        </div>
      </div>
    </section>
    <!-- ===== 登录限流 ===== -->
    <section class="panel settings-panel anim-fade-in-up">
      <h2 class="section-title">登录限流</h2>
      <el-form label-width="96px" class="limit-form" @submit.prevent>
        <el-form-item label="失败次数上限">
          <el-input-number
            v-model="form.login.failLimit"
            :min="1"
            :precision="0"
            controls-position="right"
            style="width: 180px"
          />
          <span class="form-tip">统计窗口内失败达到该次数即锁定账号</span>
        </el-form-item>
        <el-form-item label="统计窗口（秒）">
          <el-input-number
            v-model="form.login.windowSeconds"
            :min="1"
            :precision="0"
            controls-position="right"
            style="width: 180px"
          />
          <span class="form-tip">失败次数的统计时间窗口</span>
        </el-form-item>
        <el-form-item label="锁定时长（分钟）">
          <el-input-number
            v-model="lockMinutes"
            :min="1"
            :precision="0"
            controls-position="right"
            style="width: 180px"
          />
          <span class="form-tip">锁定期间即使密码正确也拒绝登录</span>
        </el-form-item>
      </el-form>
    </section>
    <!-- ===== API 限流 ===== -->
    <section class="panel settings-panel anim-fade-in-up">
      <h2 class="section-title">API 限流</h2>
      <div class="switch-row">
        <el-switch v-model="form.api.enabled" active-text="启用 API 每分钟限流" />
      </div>
      <el-table :data="roleRows" stripe size="small" class="role-table" border>
        <el-table-column prop="label" label="角色" width="170" />
        <el-table-column prop="key" label="角色标识" width="160" />
        <el-table-column label="每分钟限额（次）" width="220">
          <template #default="{ row }">
            <el-input-number
              :model-value="perMinuteOf(row)"
              :min="1"
              :precision="0"
              controls-position="right"
              :disabled="!form.api.enabled"
              style="width: 180px"
              @update:model-value="setPerMinute(row, $event)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="desc" label="说明" min-width="200" show-overflow-tooltip />
      </el-table>
    </section>
    <!-- ===== 操作（常驻底部，长页面滚动时也可达） ===== -->
    <div class="sticky-actions">
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      <el-button :loading="resetting" @click="reset">恢复默认</el-button>
      <el-button type="danger" plain :loading="clearing" @click="clearRecords">
        清空限制记录
      </el-button>
    </div>
  </div>
</template>
<style scoped>
.settings-view {
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
/* 每个分区一张面板卡片，避免整页一长条 */
.settings-panel {
  padding: 18px 20px;
}
.settings-panel .section-title {
  margin-bottom: 14px;
}
.limit-form {
  max-width: 720px;
}
.form-tip {
  margin-left: 12px;
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
}
.switch-row {
  margin-bottom: 12px;
}
/* 页面本身用 gap 排版，操作条不再叠加全局 margin-top */
.settings-view .sticky-actions {
  margin-top: 0;
}
.role-table {
  max-width: 860px;
}
@media (max-width: 640px) {
  .form-tip {
    display: block;
    margin-left: 0;
    margin-top: 2px;
  }
}
</style>