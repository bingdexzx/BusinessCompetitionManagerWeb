<script setup lang="ts">
// 个人档案：基本信息 / 我的比赛身份 / 参赛记录与获奖（电子奖牌） / 登录设备
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Edit, Medal, Refresh } from '@element-plus/icons-vue'
import { getMedal, getMyAwards, getMyDevices, getSchools } from '@/api'
import type { AwardRecord, MedalAsset, Membership, MyDevice, School } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

const auth = useAuthStore()
const user = computed(() => auth.user)

// ---------- 标签映射 ----------
const STATUS_LABELS: Record<string, string> = {
  CREATED: '已创建',
  PACKAGE_IMPORTED: '已导入比赛包',
  ENROLLING: '报名中',
  RUNNING: '进行中',
  SETTLING: '结算中',
  CLOSED: '已结束',
}

function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

function statusTagType(status: string): TagType {
  if (status === 'RUNNING') return 'success'
  if (status === 'ENROLLING') return 'primary'
  if (status === 'CLOSED') return 'info'
  return 'warning'
}

function awardTagType(level: string): TagType {
  const l = (level || '').toUpperCase()
  if (/GOLD|一等|冠军/.test(l)) return 'warning'
  if (/SILVER|二等|亚军/.test(l)) return 'info'
  if (/BRONZE|三等|季军/.test(l)) return 'success'
  if (/SPECIAL|特等/.test(l)) return 'danger'
  return 'primary'
}

/** 奖项类型标签配色：个人奖 = primary，集体奖 = success（与结算页口径一致） */
function awardKindTagType(kind: string): TagType {
  return kind === 'COLLECTIVE' ? 'success' : 'primary'
}

// ---------- 基本信息（编辑弹窗） ----------
const editVisible = ref(false)
const saving = ref(false)
const form = reactive({ displayName: '', email: '', schoolId: null as number | null })
const schools = ref<School[]>([])
const schoolsLoading = ref(false)

async function loadSchools(q: string): Promise<void> {
  schoolsLoading.value = true
  try {
    schools.value = await getSchools(q || undefined)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    schoolsLoading.value = false
  }
}

function openEdit(): void {
  form.displayName = user.value?.displayName ?? ''
  form.email = user.value?.email ?? ''
  form.schoolId = user.value?.school ?? null
  editVisible.value = true
  if (schools.value.length === 0) void loadSchools('')
}

async function saveProfile(): Promise<void> {
  const email = form.email.trim()
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    ElMessage.warning('请输入有效的邮箱地址')
    return
  }
  saving.value = true
  try {
    await auth.updateProfile({
      displayName: form.displayName.trim(),
      email,
      schoolId: form.schoolId,
    })
    ElMessage.success('个人信息已保存')
    editVisible.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    saving.value = false
  }
}

// ---------- 参赛记录与获奖 ----------
const awards = ref<AwardRecord[]>([])
const awardsLoading = ref(false)

async function loadAwards(): Promise<void> {
  awardsLoading.value = true
  try {
    awards.value = await getMyAwards()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    awardsLoading.value = false
  }
}

// ---------- 电子奖牌（仅在线展示，按需拉取） ----------
const medalVisible = ref(false)
const medalLoading = ref(false)
const medal = ref<MedalAsset | null>(null)
const medalRecord = ref<AwardRecord | null>(null)

async function openMedal(row: AwardRecord): Promise<void> {
  if (!row.medalId) return
  medalRecord.value = row
  medal.value = null
  medalVisible.value = true
  medalLoading.value = true
  try {
    medal.value = await getMedal(row.medalId)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    medalLoading.value = false
  }
}

// ---------- 登录设备 ----------
const devices = ref<MyDevice[]>([])
const devicesLoading = ref(false)

async function loadDevices(): Promise<void> {
  devicesLoading.value = true
  try {
    devices.value = await getMyDevices()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    devicesLoading.value = false
  }
}

function identityTagType(identity: string): TagType {
  if (identity === 'COMP_SUPER_ADMIN') return 'danger'
  if (identity === 'ADMIN') return 'warning'
  return 'primary'
}

function membershipTagType(m: Membership): TagType {
  return identityTagType(m.identity)
}

onMounted(() => {
  void loadAwards()
  void loadDevices()
})
</script>

<template>
  <div class="profile-view anim-stagger">
    <h1 class="page-title">个人档案</h1>

    <!-- 基本信息 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">基本信息</h2>
          <el-button type="primary" :icon="Edit" @click="openEdit">编辑资料</el-button>
        </div>
      </template>
      <el-descriptions :column="2" border size="default">
        <el-descriptions-item label="用户名">{{ user?.username ?? '—' }}</el-descriptions-item>
        <el-descriptions-item label="显示名">{{ user?.displayName || '—' }}</el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ user?.email || '—' }}</el-descriptions-item>
        <el-descriptions-item label="学校">{{ user?.schoolName || '—' }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">
          <span class="value-num">{{ formatDateTime(user?.dateJoined) }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="账号角色">
          <el-tag size="small" :type="user?.isSuperuser ? 'danger' : 'info'">
            {{ user?.isSuperuser ? '系统超管' : '普通用户' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 我的比赛身份 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">
            我的比赛身份
            <span class="count-tip value-num">共 {{ auth.memberships.length }} 项</span>
          </h2>
          <el-button :icon="Refresh" @click="auth.fetchMe()">刷新</el-button>
        </div>
      </template>
      <el-table :data="auth.memberships" stripe size="default">
        <el-table-column prop="competitionName" label="比赛" min-width="180" show-overflow-tooltip />
        <el-table-column label="身份" width="160">
          <template #default="{ row }">
            <el-tag size="small" :type="membershipTagType(row)">{{ row.identityLabel }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="所辖公司" min-width="180">
          <template #default="{ row }">
            <template v-if="(row.managedCompanies ?? []).length">
              <el-tag v-for="cid in row.managedCompanies" :key="cid" size="small" class="company-tag">
                公司 #{{ cid }}
              </el-tag>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="比赛状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.competitionStatus)">
              {{ statusLabel(row.competitionStatus) }}
            </el-tag>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无比赛身份" :image-size="72" />
        </template>
      </el-table>
    </el-card>

    <!-- 参赛记录与获奖 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">
            参赛记录与获奖
            <span class="count-tip value-num">共 {{ awards.length }} 项</span>
          </h2>
          <el-button :icon="Refresh" @click="loadAwards">刷新</el-button>
        </div>
      </template>
      <!-- 奖项做成徽章卡片：一眼看到「什么奖 · 哪场比赛 · 有无电子奖牌」 -->
      <div v-if="awardsLoading && !awards.length" class="award-grid">
        <div v-for="i in 3" :key="i" class="skeleton award-skeleton" />
      </div>
      <el-empty v-else-if="!awards.length" description="暂无参赛与获奖记录" :image-size="72" />
      <div v-else class="award-grid anim-stagger">
        <article v-for="row in awards" :key="row.id" class="award-card">
          <div class="award-emblem">
            <el-icon><Medal /></el-icon>
          </div>
          <div class="award-body">
            <div class="award-head">
              <span class="award-name" :title="row.awardName">{{ row.awardName || '—' }}</span>
              <el-tag size="small" :type="awardKindTagType(row.awardKind)" effect="plain">
                {{ row.awardKindLabel || '—' }}
              </el-tag>
            </div>
            <div class="award-competition">{{ row.competitionName }}</div>
            <div class="award-meta">
              <span class="award-meta-item">公司：{{ row.teamName || '—' }}</span>
              <span class="award-meta-item">奖牌：{{ row.medalName || '—' }}</span>
              <span class="award-meta-item value-num">
                获得时间：{{ formatDateTime(row.createdAt) }}
              </span>
            </div>
            <el-button
              link
              type="primary"
              size="small"
              :icon="Medal"
              :disabled="!row.medalId"
              @click="openMedal(row)"
            >
              查看电子奖牌
            </el-button>
          </div>
        </article>
      </div>
    </el-card>

    <!-- 登录设备 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">
            登录设备
            <span class="count-tip value-num">共 {{ devices.length }} 台</span>
          </h2>
          <el-button :icon="Refresh" @click="loadDevices">刷新</el-button>
        </div>
      </template>
      <el-table :data="devices" v-loading="devicesLoading" stripe size="default">
        <el-table-column prop="os" label="操作系统" min-width="120" show-overflow-tooltip />
        <el-table-column prop="browser" label="浏览器" min-width="120" show-overflow-tooltip />
        <el-table-column prop="screen" label="屏幕" width="110" />
        <el-table-column label="IP" min-width="130">
          <template #default="{ row }">
            <span class="value-num">{{ row.ip || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="首次登录" min-width="160">
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.firstLoginAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最近登录" min-width="160">
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.lastLoginAt) }}</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无设备记录" :image-size="72" />
        </template>
      </el-table>
    </el-card>

    <!-- 编辑资料弹窗 -->
    <el-dialog v-model="editVisible" title="编辑资料" width="480px" destroy-on-close>
      <el-form :model="form" label-width="80px">
        <el-form-item label="显示名">
          <el-input v-model="form.displayName" placeholder="显示名" maxlength="50" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="name@example.com" />
        </el-form-item>
        <el-form-item label="学校">
          <el-select
            v-model="form.schoolId"
            filterable
            remote
            clearable
            :remote-method="loadSchools"
            :loading="schoolsLoading"
            placeholder="输入搜索学校"
            style="width: 100%"
          >
            <el-option v-for="s in schools" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveProfile">保存</el-button>
      </template>
    </el-dialog>

    <!-- 电子奖牌弹窗：displayAsset 为服务端下发 SVG，仅在线展示（不提供下载） -->
    <el-dialog v-model="medalVisible" title="电子奖牌" width="420px" destroy-on-close>
      <div v-loading="medalLoading" class="medal-card">
        <div class="medal-asset" v-html="medal?.displayAsset ?? ''"></div>
        <div class="medal-name">{{ medal?.displayName || medalRecord?.medalName || '电子奖牌' }}</div>
        <div class="medal-meta">
          <el-tag size="small" :type="awardTagType(medal?.awardLevel ?? medalRecord?.awardName ?? '')">
            {{ medal?.awardLevel ?? medalRecord?.awardName ?? '—' }}
          </el-tag>
          <span class="muted">{{ medalRecord?.competitionName }}</span>
        </div>
      </div>
      <div class="medal-note">电子奖牌仅在线展示（不提供下载）</div>
    </el-dialog>
  </div>
</template>

<style scoped>
.profile-view {
  display: flex;
  flex-direction: column;
}

/* 弹窗自带进出场动画，不参与分区入场错峰（否则打开时会多等一个错峰延迟） */
.profile-view > :deep(.el-overlay) {
  animation: none !important;
}

.section-card {
  margin-bottom: 16px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

/* 卡片标题统一用 section-title（无下边距，配合卡片头部） */
.card-head .section-title {
  margin-bottom: 0;
}

.count-tip {
  font-size: var(--font-xs);
  font-weight: 400;
  color: var(--color-text-tertiary);
}

/* ===== 奖项徽章卡片 ===== */
.award-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.award-skeleton {
  height: 116px;
}

.award-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--dur-base) var(--ease-out-expo),
    border-color var(--dur-base) var(--ease-standard);
}

.award-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--color-border-strong);
}

.award-emblem {
  flex: 0 0 40px;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--gradient-brand-soft);
  color: var(--color-primary);
  font-size: 20px;
}

.award-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.award-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  width: 100%;
}

.award-name {
  font-size: var(--font-md);
  font-weight: 700;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.award-competition {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}

.award-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 2px 12px;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}

.company-tag {
  margin: 2px 6px 2px 0;
}

.muted {
  color: var(--color-text-tertiary);
}

/* 电子奖牌徽章卡片 */
.medal-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 20px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--gradient-brand-soft), var(--color-surface-2);
  min-height: 220px;
  justify-content: center;
}

.medal-asset {
  width: 160px;
  height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* displayAsset 为内联 SVG：限制尺寸避免溢出 */
.medal-asset :deep(svg) {
  max-width: 100%;
  max-height: 100%;
}

.medal-name {
  font-size: var(--font-lg);
  font-weight: 700;
  color: var(--color-text-primary);
}

.medal-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.medal-note {
  margin-top: 12px;
  text-align: center;
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}
</style>
