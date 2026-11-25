<script setup lang="ts">
import { sanitizeMarkup } from '@/utils/sanitize'
// 个人档案：基本信息 / 参赛获奖记录（电子奖牌） / 我的纪念券
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage } from 'element-plus'
import { Edit, Medal, Refresh } from '@element-plus/icons-vue'
import { getMedal, getMyAwards, getMyTickets, getSchools } from '@/api'
import JoinTicketOverlay from '@/components/competition/JoinTicketOverlay.vue'
import { uploadFile } from '@/api/filesApi'
import type { AwardRecord, MedalAsset, MyTicket, School } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useAuthedImage } from '@/composables/useAuthedImage'
const auth = useAuthStore()
const user = computed(() => auth.user)
const avatarSrc = useAuthedImage(() => user.value?.avatar)
// ---------- 标签映射 ----------
type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

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
const avatarUploading = ref(false)
const avatarInputRef = ref<HTMLInputElement | null>(null)
const form = reactive({
  displayName: '',
  avatar: '',
  email: '',
  schoolId: null as number | null,
})
const formAvatarSrc = useAuthedImage(() => form.avatar)
const avatarInitial = computed(
  () =>
    (user.value?.displayName || user.value?.username || '?')
      .trim()
      .charAt(0)
      .toUpperCase() || '?',
)
const schools = ref<School[]>([])
const schoolsLoading = ref(false)
async function loadSchools(q: string): Promise<void> {
  schoolsLoading.value = true
  try {
    schools.value = await getSchools(q || undefined)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    schoolsLoading.value = false
  }
}
function openEdit(): void {
  form.displayName = user.value?.displayName ?? ''
  form.avatar = user.value?.avatar ?? ''
  form.email = user.value?.email ?? ''
  form.schoolId = user.value?.school ?? null
  editVisible.value = true
  if (schools.value.length === 0) void loadSchools('')
}
function pickAvatar(): void {
  avatarInputRef.value?.click()
}
async function onAvatarSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请选择图片文件')
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('头像不能超过 5MB')
    return
  }
  avatarUploading.value = true
  try {
    const uploaded = await uploadFile(file)
    form.avatar = uploaded.url
    ElMessage.success('头像已上传')
  } catch (err) {
    ElMessage.error(errorMessage(err, '头像上传失败'))
  } finally {
    avatarUploading.value = false
  }
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
      avatar: form.avatar,
      email,
      schoolId: form.schoolId,
    })
    ElMessage.success('个人信息已保存')
    editVisible.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    saving.value = false
  }
}
// ---------- 我的纪念券 ----------
const tickets = ref<MyTicket[]>([])
const ticketsLoading = ref(false)

async function loadTickets(): Promise<void> {
  ticketsLoading.value = true
  try {
    tickets.value = await getMyTickets()
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    ticketsLoading.value = false
  }
}

// ---------- 参赛获奖记录 ----------
const awards = ref<AwardRecord[]>([])
const awardsLoading = ref(false)
async function loadAwards(): Promise<void> {
  awardsLoading.value = true
  try {
    awards.value = await getMyAwards()
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
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
onMounted(() => {
  void loadTickets()
  void loadAwards()
})
// 奖项发放/奖牌变更/管理员改资料后自动重拉（资源名与后端按路径推导的一致）
useResourceRefresh(['awards', 'medals', 'users'], () => {
  void loadAwards()
  void loadTickets()
  void auth.fetchMe()
})
</script>
<template>
  <div class="profile-view anim-stagger page">
    <PageHeader title="个人档案" />
    <!-- 基本信息 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">基本信息</h2>
          <el-button type="primary" :icon="Edit" @click="openEdit">编辑资料</el-button>
        </div>
      </template>
      <div class="profile-hero">
        <el-avatar :size="76" :src="avatarSrc" class="profile-avatar">
          {{ avatarInitial }}
        </el-avatar>
        <div class="profile-hero-text">
          <h2 class="profile-name">{{ user?.displayName || user?.username || '用户' }}</h2>
          <p class="profile-sub">
            @{{ user?.username || '—' }}
            <span v-if="user?.schoolName"> · {{ user.schoolName }}</span>
          </p>
        </div>
      </div>
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
            {{ user?.isSuperuser ? '超级管理员' : '普通用户' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
    <!-- 我的纪念券：盒子保留，票面本身不带渐变底 -->
    <el-card shadow="never" class="section-card tickets-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">
            我的纪念券
            <span class="count-tip value-num">共 {{ tickets.length }} 张</span>
          </h2>
          <el-button :icon="Refresh" @click="loadTickets">刷新</el-button>
        </div>
      </template>
      <div v-if="ticketsLoading && !tickets.length" class="ticket-grid">
        <div v-for="i in 3" :key="i" class="skeleton ticket-skeleton" />
      </div>
      <el-empty
        v-else-if="!tickets.length"
        description="加入比赛后会生成你的纪念券"
        :image-size="72"
      />
      <div v-else class="ticket-grid anim-stagger">
        <div v-for="ticket in tickets" :key="ticket.competitionId" class="ticket-item">
          <JoinTicketOverlay
            bare
            stub
            :show-tear-handle="false"
            :competition-id="ticket.competitionId"
            :competition-name="ticket.competitionName"
            :identity-label="ticket.identityLabel"
            :user-name="ticket.userName"
            :joined-at="ticket.joinedAt"
            :ticket-image="ticket.ticketImage"
            :ticket-no="ticket.ticketNo"
          />
        </div>
      </div>
    </el-card>
    <!-- 参赛获奖记录 -->
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <h2 class="section-title">
            参赛获奖记录
            <span class="count-tip value-num">共 {{ awards.length }} 项</span>
          </h2>
          <el-button :icon="Refresh" @click="loadAwards">刷新</el-button>
        </div>
      </template>
      <!-- 奖项做成徽章卡片：一眼看到「什么奖 · 哪场比赛 · 有无电子奖牌」 -->
      <div v-if="awardsLoading && !awards.length" class="award-grid">
        <div v-for="i in 3" :key="i" class="skeleton award-skeleton" />
      </div>
      <el-empty v-else-if="!awards.length" description="暂无获奖记录" :image-size="72" />
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
    <!-- 编辑资料弹窗 -->
    <el-dialog v-model="editVisible" title="编辑资料" width="560px" destroy-on-close>
      <el-form :model="form" label-width="96px">
        <el-form-item label="头像">
          <div class="avatar-edit">
            <el-avatar :size="56" :src="formAvatarSrc" class="profile-avatar">
              {{ avatarInitial }}
            </el-avatar>
            <input
              ref="avatarInputRef"
              type="file"
              accept="image/*"
              class="avatar-file"
              @change="onAvatarSelected"
            />
            <el-button size="small" :loading="avatarUploading" @click="pickAvatar">
              上传头像
            </el-button>
            <el-button
              v-if="form.avatar"
              size="small"
              link
              type="danger"
              @click="form.avatar = ''"
            >
              移除
            </el-button>
          </div>
          <div class="form-tip">支持 JPG / PNG / WebP，建议 1:1，最大 5MB</div>
        </el-form-item>
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
        <div class="medal-asset" v-html="sanitizeMarkup(medal?.displayAsset)"></div>
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
.profile-hero {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 2px 2px 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--color-border);
}
.profile-avatar {
  flex: 0 0 auto;
  border: 1px solid var(--color-border);
  background: var(--gradient-brand-soft);
  color: var(--color-primary);
  font-size: 28px;
  font-weight: 600;
}
.profile-hero-text {
  min-width: 0;
}
.profile-name {
  margin: 0;
  color: var(--color-text-primary);
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.profile-sub {
  margin: 4px 0 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.avatar-edit {
  display: flex;
  align-items: center;
  gap: 10px;
}
.avatar-file {
  display: none;
}
.form-tip {
  margin-top: 6px;
  color: var(--color-text-tertiary);
  font-size: 12px;
  line-height: 1.4;
}
.count-tip {
  font-size: var(--font-xs);
  font-weight: 400;
  color: var(--color-text-tertiary);
}
/* ===== 我的纪念券（无背景卡片，票面直接铺在页面上） ===== */
/* 纪念券整块强制纯白：卡片、正文、网格、票座都不要再透出页面底色 */
.tickets-card,
.tickets-card :deep(.el-card__body),
.ticket-grid,
.ticket-item {
  background: var(--color-surface);
}

.ticket-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
  gap: 16px;
}

.ticket-skeleton {
  height: 300px;
}

.ticket-item {
  min-width: 0;
}

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