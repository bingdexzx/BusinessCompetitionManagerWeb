<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules, UploadFile } from 'element-plus'
import * as api from '@/api'
import { uploadFile as uploadFileApi } from '@/api/filesApi'
import { ApiError } from '@/api/client'
import {
  COMPETITION_STATUS_CHAIN,
  MEMBER_IDENTITIES,
  MEMBER_IDENTITY_LABELS,
  type Competition,
  type CompetitionMember,
  type ImportReport,
  type InviteCode,
  type MemberIdentity,
  type PackageRecord,
  type School,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { useCatalog } from '@/composables/useCatalog'
import { useResourceRefresh } from '@/composables/useNotifications'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import FiscalYearBadge from '@/components/common/FiscalYearBadge.vue'
import JoinTicketOverlay from '@/components/competition/JoinTicketOverlay.vue'
import { useAuthedImage } from '@/composables/useAuthedImage'
const props = defineProps<{ cid: string }>()
const router = useRouter()
const auth = useAuthStore()
// 产业键 → 中文名（导入报告里不显示 manufacturer 这类 key）
const { industryLabel, contractTypeLabel } = useCatalog(() => props.cid)
/** 导入报告里的插件中文名：新报告带 name；历史报告按 kind 从目录反查 */
function pluginLabel(row: { name?: string; key?: string; kind?: string }): string {
  const key = String(row.key ?? '')
  if (row.name) return row.name
  if (row.kind === 'INDUSTRY') return industryLabel(key) || key
  if (row.kind === 'CONTRACT') return contractTypeLabel(key) || key
  return key
}
const competition = ref<Competition | null>(null)
const loading = ref(false)
const activeTab = ref('package')
// 可编辑信息/推进生命周期/激活码/成员管理：系统超级管理员（比赛超级管理员身份已取消，2026-11）
const canManage = computed(() => auth.isSuperuser)
const isSystemAdmin = computed(() => auth.isSuperuser)
const STATUS_LABELS: Record<string, string> = {
  CREATED: '已创建',
  PACKAGE_IMPORTED: '比赛包已导入',
  ENROLLING: '报名中',
  RUNNING: '进行中',
  SETTLING: '结算中',
  CLOSED: '已关闭',
}
const statusChain = COMPETITION_STATUS_CHAIN
const statusIndex = computed(() =>
  (statusChain as readonly string[]).indexOf(competition.value?.status ?? ''),
)
const statusStep = computed(() => {
  const index = statusIndex.value
  if (index < 0) return 1
  return Math.min(index + 1, statusChain.length)
})
function statusText(status: string): string {
  return STATUS_LABELS[status] ?? status
}
function statusTagType(status: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' {
  switch (status) {
    case 'ENROLLING':
      return 'warning'
    case 'RUNNING':
      return 'success'
    case 'SETTLING':
      return 'warning'
    case 'CLOSED':
      return 'info'
    default:
      return 'info'
  }
}
interface NextAction {
  target: string
  label: string
  confirmText: string
}
const NEXT_ACTIONS: Record<string, NextAction> = {
  PACKAGE_IMPORTED: {
    target: 'ENROLLING',
    label: '报名',
    confirmText: '确认推进到「报名中」？推进后选手可开始报名。',
  },
  ENROLLING: {
    target: 'RUNNING',
    label: '开赛',
    confirmText: '确认开赛？比赛进入「进行中」，报名截止。',
  },
  RUNNING: {
    target: 'SETTLING',
    label: '结束比赛并结算',
    confirmText: '确认结束比赛并进入结算？',
  },
  SETTLING: {
    target: 'CLOSED',
    label: '结算已完成关闭',
    confirmText: '确认结算已完成并关闭比赛？关闭后不可再推进。',
  },
}
const nextAction = computed(() => {
  const status = competition.value?.status ?? ''
  return NEXT_ACTIONS[status]
})
async function doTransition(action: NextAction): Promise<void> {
  try {
    await ElMessageBox.confirm(action.confirmText, '推进生命周期', {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    competition.value = await api.transitionCompetition(props.cid, action.target)
    ElMessage.success(`比赛已推进至「${statusText(action.target)}」`)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}
const showEdit = ref(false)
const editing = ref(false)
const editRef = ref<FormInstance>()
const editForm = ref({
  name: '',
  code: '',
  coverImage: '',
  ticketImage: '',
  hostSchoolIds: [] as number[],
  location: '',
})
const coverUploading = ref(false)
// 受保护文件需带 token 拉取后再预览（<img> 不会带 Authorization）
const coverPreviewSrc = useAuthedImage(() => editForm.value.coverImage)
const ticketImagePreviewSrc = useAuthedImage(() => editForm.value.ticketImage)
const ticketImageUploading = ref(false)
/** 纪念票图：铺在加入比赛时那张票的左侧主票上 */
async function onTicketImageSelected(file: UploadFile): Promise<void> {
  const raw = file.raw
  if (!raw) return
  if (!/^image\//.test(raw.type)) {
    ElMessage.warning('请选择图片文件')
    return
  }
  ticketImageUploading.value = true
  try {
    const uploaded = await uploadFileApi(raw)
    editForm.value.ticketImage = uploaded.url
    ElMessage.success('纪念票图已上传')
  } catch (err) {
    ElMessage.error(errorMessage(err, '上传失败'))
  } finally {
    ticketImageUploading.value = false
  }
}
/** 封面图：上传图片到文件服务，回填 url */
async function onCoverSelected(file: UploadFile): Promise<void> {
  const raw = file.raw
  if (!raw) return
  if (!/^image\//.test(raw.type)) {
    ElMessage.warning('请选择图片文件')
    return
  }
  coverUploading.value = true
  try {
    const uploaded = await uploadFileApi(raw)
    editForm.value.coverImage = uploaded.url
    ElMessage.success('封面图已上传')
  } catch (err) {
    ElMessage.error(errorMessage(err, '上传失败'))
  } finally {
    coverUploading.value = false
  }
}
const editRules: FormRules = {
  name: [{ required: true, message: '请输入比赛名称', trigger: 'blur' }],
  hostSchoolIds: [
    { required: true, type: 'array', min: 1, message: '请选择至少一所办赛学校', trigger: 'change' },
  ],
}
const schools = ref<School[]>([])
const schoolsLoading = ref(false)
async function openEdit(): Promise<void> {
  const comp = competition.value
  if (!comp) return
  editForm.value = {
    name: comp.name,
    code: comp.code,
    coverImage: comp.coverImage,
    ticketImage: comp.ticketImage ?? '',
    hostSchoolIds: [...(comp.hostSchoolIds ?? [])],
    location: comp.location,
  }
  showEdit.value = true
  schoolsLoading.value = true
  try {
    schools.value = await api.getSchools()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    schoolsLoading.value = false
  }
}
async function submitEdit(): Promise<void> {
  try {
    await editRef.value?.validate()
  } catch {
    return
  }
  editing.value = true
  try {
    competition.value = await api.updateCompetitionMeta(props.cid, {
      name: editForm.value.name.trim(),
      code: editForm.value.code.trim() || undefined,
      coverImage: editForm.value.coverImage.trim(),
      ticketImage: editForm.value.ticketImage.trim(),
      hostSchoolIds: editForm.value.hostSchoolIds,
      location: editForm.value.location.trim() || undefined,
    })
    ElMessage.success('比赛信息已更新')
    showEdit.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    editing.value = false
  }
}
const uploadFile = ref<File | null>(null)
const importing = ref(false)
const activeReport = ref<ImportReport | null>(null)
const packages = ref<PackageRecord[]>([])
const packagesLoading = ref(false)
function handleFileChange(file: UploadFile): void {
  const raw = file.raw ?? null
  if (raw && !raw.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('仅支持 .zip 比赛包')
    uploadFile.value = null
    return
  }
  uploadFile.value = raw
}
// limit=1 时再次选文件走 on-exceed，直接替换为新文件
function handleFileExceed(files: File[]): void {
  const raw = files[0] ?? null
  if (raw && !raw.name.toLowerCase().endsWith('.zip')) {
    ElMessage.warning('仅支持 .zip 比赛包')
    return
  }
  uploadFile.value = raw
  if (raw) ElMessage.info(`已选择：${raw.name}`)
}
function handleFileRemove(): void {
  uploadFile.value = null
}
const importAsync = ref(false)
const importProgress = ref(0)
const importMessage = ref('')
async function doImport(): Promise<void> {
  const file = uploadFile.value
  if (!file) {
    ElMessage.warning('请先选择比赛包 .zip 文件')
    return
  }
  importing.value = true
  if (importAsync.value) {
    importProgress.value = 0
    importMessage.value = '已提交后台导入任务'
    try {
      const { job } = await api.importCompetitionPackageAsync(props.cid, file)
      const finalJob = await api.waitJob(props.cid, job.id, (current) => {
        importProgress.value = current.progress
        importMessage.value = current.message || current.statusLabel
      })
      if (finalJob.status === 'FAILED') {
        ElMessage.error(finalJob.error || '后台导入失败')
      } else {
        ElMessage.success('比赛包导入成功')
      }
      await Promise.all([loadCompetition(), loadPackages()])
    } catch (e) {
      ElMessage.error(errorMessage(e, '导入失败'))
    } finally {
      importing.value = false
      importMessage.value = ''
      importProgress.value = 0
    }
    return
  }
  try {
    const record = await api.importCompetitionPackage(props.cid, file)
    activeReport.value = record.report
    if (record.status === 'SUCCESS') {
      ElMessage.success('比赛包导入成功')
      await Promise.all([loadCompetition(), loadPackages()])
    } else {
      ElMessage.error('比赛包导入失败：请查看导入报告')
      await loadPackages()
    }
    uploadFile.value = null
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    importing.value = false
  }
}
async function loadPackages(): Promise<void> {
  packagesLoading.value = true
  try {
    packages.value = await api.getCompetitionPackages(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    packagesLoading.value = false
  }
}
const basedataEntries = computed(() => {
  const rows = activeReport.value?.basedataRows ?? {}
  return Object.entries(rows).map(([key, count]) => ({ key, count }))
})
function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 12) : '—'
}
const members = ref<CompetitionMember[]>([])
const membersLoading = ref(false)
const showAssign = ref(false)
const assigning = ref(false)
const assignForm = ref({
  username: '',
  identity: 'PLAYER' as MemberIdentity,
  managedCompanies: '',
})
const showEditMember = ref(false)
const editingMember = ref(false)
const editMemberTarget = ref<CompetitionMember | null>(null)
const editMemberForm = ref({
  identity: 'PLAYER' as MemberIdentity,
  managedCompanies: '',
  isActive: true,
})
function parseCompanies(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((s) => Number(s.trim()))
    .filter((n) => Number.isInteger(n) && n > 0)
}
async function loadMembers(): Promise<void> {
  membersLoading.value = true
  try {
    members.value = await api.getCompetitionMembers(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    membersLoading.value = false
  }
}
async function submitAssign(): Promise<void> {
  const username = assignForm.value.username.trim()
  if (!username) {
    ElMessage.warning('请输入用户名')
    return
  }
  assigning.value = true
  try {
    await api.assignCompetitionMember(props.cid, {
      username,
      identity: assignForm.value.identity,
      managedCompanies: parseCompanies(assignForm.value.managedCompanies),
    })
    ElMessage.success('成员已指派')
    showAssign.value = false
    await loadMembers()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    assigning.value = false
  }
}
function openEditMember(row: CompetitionMember): void {
  editMemberTarget.value = row
  editMemberForm.value = {
    identity: row.identity as MemberIdentity,
    managedCompanies: (row.managedCompanies ?? []).join(', '),
    isActive: row.isActive,
  }
  showEditMember.value = true
}
async function submitEditMember(): Promise<void> {
  const target = editMemberTarget.value
  if (!target) return
  editingMember.value = true
  try {
    await api.updateCompetitionMember(props.cid, target.id, {
      identity: editMemberForm.value.identity,
      managedCompanies: parseCompanies(editMemberForm.value.managedCompanies),
      isActive: editMemberForm.value.isActive,
    })
    ElMessage.success('成员信息已更新')
    showEditMember.value = false
    await loadMembers()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    editingMember.value = false
  }
}
const invites = ref<InviteCode[]>([])
const invitesLoading = ref(false)
const showCreateInvite = ref(false)
const creatingInvite = ref(false)
const inviteForm = ref({
  identity: 'PLAYER' as MemberIdentity,
  maxUses: 1,
  validDays: 7,
  note: '',
})
async function loadInvites(): Promise<void> {
  invitesLoading.value = true
  try {
    invites.value = await api.getInviteCodes(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载失败'))
  } finally {
    invitesLoading.value = false
  }
}
async function submitCreateInvite(): Promise<void> {
  creatingInvite.value = true
  try {
    const invite = await api.createInviteCode(props.cid, {
      identity: inviteForm.value.identity,
      maxUses: inviteForm.value.maxUses,
      validDays: inviteForm.value.validDays,
      note: inviteForm.value.note.trim() || undefined,
    })
    ElMessage.success(`激活码已生成：${invite.code}`)
    showCreateInvite.value = false
    await loadInvites()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    creatingInvite.value = false
  }
}
async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('内容已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败：请手动复制')
  }
}
function quickLink(path: string): void {
  void router.push(`/competitions/${props.cid}${path}`)
}
const missing = ref(false)
// 加载失败就地提示并支持重试（ElMessage 同时保留）
const loadError = ref('')
async function loadCompetition(): Promise<void> {
  loading.value = true
  try {
    competition.value = await api.getCompetition(props.cid)
    missing.value = false
    loadError.value = ''
    auth.selectCompetition(props.cid)
  } catch (err) {
    // 404 视为比赛已删除，展示友好状态
    if (err instanceof ApiError && err.status === 404) {
      missing.value = true
      competition.value = null
      return
    }
    const message = errorMessage(err, '加载失败')
    loadError.value = message
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}
watch(
  () => props.cid,
  () => {
    activeReport.value = null
    void loadCompetition()
    void loadPackages()
    if (isSystemAdmin.value) void loadMembers()
    if (canManage.value) void loadInvites()
  },
)
// 比赛/成员/队伍/用户/激活码/比赛包变更后 400ms 去抖重拉，按权限决定加载范围
useResourceRefresh(['competitions', 'members', 'teams', 'users', 'invites', 'packages'], () => {
  void loadCompetition()
  void loadPackages()
  if (isSystemAdmin.value) void loadMembers()
  if (canManage.value) void loadInvites()
})
onMounted(() => {
  void loadCompetition()
  void loadPackages()
  if (isSystemAdmin.value) void loadMembers()
  if (canManage.value) void loadInvites()
})
</script>
<template>
  <el-alert
    v-if="missing"
    type="error"
    show-icon
    :closable="false"
    title="比赛不存在或已删除"
    description="请返回比赛列表重新选择"
  >
    <template #default>
      <el-button type="primary" size="small" @click="$router.push('/competitions')">
        返回比赛列表
      </el-button>
    </template>
  </el-alert>
  <el-alert
    v-else-if="loadError"
    type="error"
    show-icon
    :closable="false"
    :title="loadError"
    class="detail-alert"
  >
    <el-button size="small" @click="loadCompetition">重试</el-button>
  </el-alert>
  <div v-if="loading && !competition" class="detail-skeleton page" aria-busy="true">
    <div class="skeleton skeleton-line detail-skeleton__title" />
    <div class="detail-skeleton__cards">
      <div v-for="n in 3" :key="`sk-card-${n}`" class="skeleton detail-skeleton__card" />
    </div>
    <div class="skeleton skeleton-line" />
    <div class="skeleton skeleton-line" />
  </div>
  <div v-if="competition" class="detail-page">
    <PageHeader :title="competition.name">
      <template #meta>
        <FiscalYearBadge :cid="props.cid" />
      </template>
      <template #actions>
        <el-button v-if="canManage" @click="openEdit">
          <el-icon><Edit /></el-icon>
          <span>编辑信息</span>
        </el-button>
      </template>
    </PageHeader>
    <el-card class="info-card anim-fade-in-up" shadow="never">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="比赛编码">
          <span class="mono">{{ competition.code || '—' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusTagType(competition.status)">{{ competition.statusLabel }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="地点">{{ competition.location || '—' }}</el-descriptions-item>
        <el-descriptions-item label="办赛学校">
          {{ competition.hostSchoolNames?.join('、') || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">
          {{ formatDateTime(competition.createdAt) }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>
    <el-card class="lifecycle-card anim-fade-in-up" style="--anim-delay: 60ms" shadow="never">
      <template #header>
        <div class="lifecycle-head">
          <span>生命周期</span>
          <el-tag :type="statusTagType(competition.status)" size="small">
            {{ competition.statusLabel }}
          </el-tag>
          <span class="lifecycle-step-count">第 {{ statusStep }} / {{ statusChain.length }} 步</span>
        </div>
      </template>
      <div class="lifecycle-steps-scroll">
        <el-steps
          class="lifecycle-steps"
          :active="competition.status === 'CLOSED' ? statusChain.length : statusIndex"
          align-center
          finish-status="success"
        >
          <el-step v-for="s in statusChain" :key="s" :title="statusText(s)" />
        </el-steps>
      </div>
      <div class="lifecycle-actions">
        <el-alert
          v-if="competition.status === 'CREATED'"
          type="info"
          :closable="false"
          show-icon
          title="需先导入比赛包后方可推进"
        >
          <el-button size="small" type="primary" @click="activeTab = 'package'">
            去导入比赛包
          </el-button>
        </el-alert>
        <el-button
          v-else-if="canManage && nextAction"
          type="primary"
          @click="doTransition(nextAction)"
        >
          {{ nextAction.label }}
        </el-button>
        <span v-else-if="competition.status === 'CLOSED'" class="muted">比赛已关闭</span>
      </div>
    </el-card>
    <div class="quick-links anim-fade-in-up" style="--anim-delay: 100ms">
      <el-button v-if="canManage" @click="quickLink('/teams')">
        <el-icon><User /></el-icon><span>组队管理</span>
      </el-button>
      <el-button @click="quickLink('/contracts')">
        <el-icon><Tickets /></el-icon><span>合同工作台</span>
      </el-button>
      <el-button v-if="canManage" @click="quickLink('/fiscal')">
        <el-icon><Calendar /></el-icon><span>财年</span>
      </el-button>
      <el-button v-if="canManage" @click="quickLink('/settlement')">
        <el-icon><DataAnalysis /></el-icon><span>结算</span>
      </el-button>
      <!-- 字段日志含各公司成本/利润流水，只给超级管理员看（与侧栏、路由守卫口径一致） -->
      <el-button v-if="canManage" @click="quickLink('/logs')">
        <el-icon><Document /></el-icon><span>字段日志</span>
      </el-button>
    </div>
    <el-tabs v-model="activeTab" class="detail-tabs anim-fade-in-up" style="--anim-delay: 140ms">
      <el-tab-pane label="比赛包导入" name="package">
        <el-card shadow="never">
          <el-upload
            class="pkg-upload"
            drag
            accept=".zip"
            :limit="1"
            :auto-upload="false"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :on-exceed="handleFileExceed"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">将比赛包 .zip 拖到此处，或<em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">仅支持 .zip 比赛包，手动点击「开始导入」后上传</div>
            </template>
          </el-upload>
          <div class="import-actions">
            <el-button
              type="primary"
              :loading="importing"
              :disabled="importing"
              @click="doImport"
            >
              开始导入
            </el-button>
            <el-checkbox v-model="importAsync" :disabled="importing">
              后台导入（大包推荐）
            </el-checkbox>
            <span v-if="uploadFile" class="import-file">{{ uploadFile.name }}</span>
            <span v-if="importing && importAsync" class="import-progress">
              <el-progress
                :percentage="importProgress"
                :stroke-width="6"
                :show-text="false"
                class="import-progress-bar"
              />
              <span class="import-progress-text">{{ importMessage }}</span>
            </span>
          </div>
        </el-card>
        <el-card v-if="activeReport" shadow="never" class="report-card anim-fade-in-up">
          <template #header>
            <div class="report-head">
              <div class="report-head-main">
                <span class="report-title">导入报告</span>
                <el-tag :type="activeReport.status === 'SUCCESS' ? 'success' : 'danger'" size="small">
                  {{ activeReport.status === 'SUCCESS' ? '导入成功' : '导入失败' }}
                </el-tag>
              </div>
              <div class="report-head-meta">
                <span class="report-meta">
                  <span class="report-meta-label">建库</span>
                  <span class="report-meta-value">
                    {{ activeReport.createdDatabase || '未创建数据库' }}
                  </span>
                </span>
                <span class="report-meta">
                  <span class="report-meta-label">合同实例</span>
                  <span class="report-meta-value">
                    <span class="value-num">{{ activeReport.contractsCreated ?? 0 }}</span>
                    <template v-if="activeReport.contractsSkipped">
                      （跳过重复 <span class="value-num">{{ activeReport.contractsSkipped }}</span>）
                    </template>
                  </span>
                </span>
              </div>
            </div>
          </template>
          <section
            v-if="activeReport.errors?.length || activeReport.warnings?.length"
            class="report-section"
          >
            <h4 class="section-title">
              问题与提示（错误 {{ activeReport.errors?.length ?? 0 }} ·
              警告 {{ activeReport.warnings?.length ?? 0 }}）
            </h4>
            <el-alert
              v-for="(err, i) in activeReport.errors"
              :key="`err-${i}`"
              type="error"
              :title="err"
              :closable="false"
              show-icon
              class="report-alert"
            />
            <el-alert
              v-for="(warn, i) in activeReport.warnings"
              :key="`warn-${i}`"
              type="warning"
              :title="warn"
              :closable="false"
              show-icon
              class="report-alert"
            />
          </section>
          <section class="report-section">
            <h4 class="section-title">插件（{{ activeReport.plugins?.length ?? 0 }}）</h4>
            <el-table :data="activeReport.plugins" size="small" border stripe>
              <el-table-column label="名称" min-width="120">
                <template #default="{ row }">
                  {{ pluginLabel(row) }}
                </template>
              </el-table-column>
              <el-table-column prop="file" label="文件" min-width="160" />
              <el-table-column label="类型" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.kind === 'CONTRACT' ? 'primary' : 'success'">
                    {{ row.kind === 'CONTRACT' ? '合同类型' : '产业类型' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="version" label="版本" width="90" />
              <el-table-column label="SHA-256" width="130">
                <template #default="{ row }">
                  <span class="mono" :title="row.sha256">{{ shortSha(row.sha256) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
          <section class="report-section">
            <h4 class="section-title">
              字段迁移（{{ activeReport.fieldMigrations?.length ?? 0 }}）
            </h4>
            <el-table :data="activeReport.fieldMigrations" size="small" border stripe>
              <el-table-column label="产业类型" min-width="120">
                <template #default="{ row }">
                  {{ row.industryName || industryLabel(row.industryKey) }}
                </template>
              </el-table-column>
              <el-table-column label="新增字段" width="100">
                <template #default="{ row }">
                  <span class="value-num">+{{ row.added }}</span>
                </template>
              </el-table-column>
              <el-table-column label="更新字段" width="100">
                <template #default="{ row }">
                  <span class="value-num">~{{ row.updated }}</span>
                </template>
              </el-table-column>
              <el-table-column label="字段总数" width="100">
                <template #default="{ row }">
                  <span class="value-num">{{ row.total }}</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
          <section class="report-section">
            <h4 class="section-title">
              基础数据导入（{{ basedataEntries.length }} 张表）
            </h4>
            <el-table :data="basedataEntries" size="small" border stripe>
              <el-table-column prop="key" label="数据表" min-width="140" />
              <el-table-column label="导入行数" width="120">
                <template #default="{ row }">
                  <span class="value-num">{{ row.count }}</span>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-card>
        <el-card shadow="never" class="history-card">
          <template #header>导入历史</template>
          <el-table
            v-loading="packagesLoading"
            :data="packages"
            size="small"
            border
           stripe>
        <template #empty>
          <el-empty description="暂无导入记录" :image-size="72" />
        </template>
            <el-table-column prop="fileName" label="文件名" min-width="160" />
            <el-table-column label="SHA-256" width="130">
              <template #default="{ row }">
                <span class="mono" :title="row.sha256">{{ shortSha(row.sha256) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.status === 'SUCCESS' ? 'success' : 'danger'">
                  {{ row.status === 'SUCCESS' ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="createdByUsername" label="操作人" width="120" />
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="activeReport = row.report">
                  查看报告
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
      <el-tab-pane v-if="isSystemAdmin" label="成员管理" name="members">
        <el-card shadow="never">
          <div class="tab-toolbar">
            <el-button type="primary" @click="showAssign = true">
              <el-icon><Plus /></el-icon><span>指派成员</span>
            </el-button>
          </div>
          <el-table v-loading="membersLoading" :data="members" border size="small" stripe>
        <template #empty>
          <el-empty description="暂无成员" :image-size="72" />
        </template>
            <el-table-column prop="username" label="用户名" min-width="120" />
            <el-table-column prop="displayName" label="姓名" min-width="110" />
            <el-table-column label="身份" width="150">
              <template #default="{ row }">
                <el-tag size="small">{{ row.identityLabel }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="所辖公司" min-width="140">
              <template #default="{ row }">
                <template v-if="row.managedCompanies?.length">
                  <el-tag
                    v-for="c in row.managedCompanies"
                    :key="c"
                    size="small"
                    type="info"
                    class="mini-tag"
                  >
                    公司 {{ c }}
                  </el-tag>
                </template>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.isActive ? 'success' : 'danger'">
                  {{ row.isActive ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="90">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="openEditMember(row)">
                  编辑
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
      <el-tab-pane v-if="canManage" label="激活码" name="invites">
        <el-card shadow="never">
          <div class="tab-toolbar">
            <el-button type="primary" @click="showCreateInvite = true">
              <el-icon><Plus /></el-icon><span>生成激活码</span>
            </el-button>
          </div>
          <el-table v-loading="invitesLoading" :data="invites" border size="small" stripe>
        <template #empty>
          <el-empty description="暂无激活码" :image-size="72" />
        </template>
            <el-table-column label="激活码" min-width="180">
              <template #default="{ row }">
                <span class="mono">{{ row.code }}</span>
                <el-button
                  size="small"
                  link
                  type="primary"
                  class="copy-btn"
                  @click="copyText(row.code)"
                >
                  <el-icon><CopyDocument /></el-icon>复制
                </el-button>
              </template>
            </el-table-column>
            <el-table-column label="身份" width="140">
              <template #default="{ row }">
                <el-tag size="small">{{ row.identityLabel }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="使用情况" width="110">
              <template #default="{ row }">{{ row.usedCount }} / {{ row.maxUses }}</template>
            </el-table-column>
            <el-table-column label="有效期至" width="170">
              <template #default="{ row }">{{ formatDateTime(row.expiresAt) }}</template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="120">
              <template #default="{ row }">{{ row.note || '—' }}</template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="纪念券" name="ticket">
        <el-card class="ticket-preview-card" shadow="never">
          <template #header>
            <div class="ticket-preview-head">
              <span>纪念券</span>
            </div>
          </template>
          <div class="ticket-preview-body">
            <JoinTicketOverlay
              inline
              :competition-id="Number(cid) || 0"
              :competition-name="competition.name"
              :ticket-image="competition.ticketImage || ''"
              :ticket-no="1"
              user-name="示例参赛代表"
              identity-label="参赛代表"
            />
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
    <el-dialog v-model="showEdit" title="编辑比赛信息" width="560px" destroy-on-close>
      <el-form ref="editRef" :model="editForm" :rules="editRules" label-width="96px" @submit.prevent>
        <el-form-item label="比赛名称" prop="name">
          <el-input v-model="editForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="比赛编码">
          <el-input v-model="editForm.code" />
        </el-form-item>
        <el-form-item label="纪念票图">
          <div class="cover-field">
            <div class="cover-actions">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                accept="image/*"
                :on-change="onTicketImageSelected"
              >
                <el-button :loading="ticketImageUploading">
                  {{ editForm.ticketImage ? '重新上传' : '上传图片' }}
                </el-button>
              </el-upload>
              <el-button
                v-if="editForm.ticketImage"
                link
                type="danger"
                @click="editForm.ticketImage = ''"
                >移除</el-button
              >
            </div>
            <img
              v-if="ticketImagePreviewSrc"
              :src="ticketImagePreviewSrc"
              class="cover-preview"
              alt="纪念票图预览"
            />
            <p class="ticket-image-tip">这张图会铺在加入比赛时入场券的左侧主票上</p>
          </div>
        </el-form-item>
        <el-form-item label="封面图">
          <div class="cover-field">
            <div class="cover-actions">
              <el-upload
                :show-file-list="false"
                :auto-upload="false"
                accept="image/*"
                :on-change="onCoverSelected"
              >
                <el-button :loading="coverUploading">
                  {{ editForm.coverImage ? '重新上传' : '上传图片' }}
                </el-button>
              </el-upload>
              <el-button
                v-if="editForm.coverImage"
                link
                type="danger"
                @click="editForm.coverImage = ''"
                >移除</el-button
              >
            </div>
            <img
              v-if="coverPreviewSrc"
              :src="coverPreviewSrc"
              class="cover-preview"
              alt="封面图预览"
            />
          </div>
        </el-form-item>
        <el-form-item label="办赛学校" prop="hostSchoolIds">
          <el-select
            v-model="editForm.hostSchoolIds"
            multiple
            :loading="schoolsLoading"
            filterable
            clearable
            placeholder="必选，至少选择一所办赛学校"
            style="width: 100%"
          >
            <el-option v-for="s in schools" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="地点">
          <el-input v-model="editForm.location" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="showAssign" title="指派成员" width="560px" destroy-on-close>
      <el-form :model="assignForm" label-width="96px" @submit.prevent>
        <el-form-item label="用户名">
          <el-input v-model="assignForm.username" placeholder="要指派的账号用户名" />
        </el-form-item>
        <el-form-item label="身份">
          <el-select v-model="assignForm.identity" style="width: 100%">
            <el-option
              v-for="id in MEMBER_IDENTITIES"
              :key="id"
              :value="id"
              :label="MEMBER_IDENTITY_LABELS[id]"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="所辖公司">
          <el-input
            v-model="assignForm.managedCompanies"
            placeholder="可选：公司 ID，多个用逗号分隔，如 1, 2, 3"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAssign = false">取消</el-button>
        <el-button type="primary" :loading="assigning" @click="submitAssign">指派</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="showEditMember" title="编辑成员" width="560px" destroy-on-close>
      <el-form :model="editMemberForm" label-width="96px" @submit.prevent>
        <el-form-item label="身份">
          <el-select v-model="editMemberForm.identity" style="width: 100%">
            <el-option
              v-for="id in MEMBER_IDENTITIES"
              :key="id"
              :value="id"
              :label="MEMBER_IDENTITY_LABELS[id]"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="所辖公司">
          <el-input
            v-model="editMemberForm.managedCompanies"
            placeholder="公司 ID，多个用逗号分隔，如 1, 2, 3"
          />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editMemberForm.isActive" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditMember = false">取消</el-button>
        <el-button type="primary" :loading="editingMember" @click="submitEditMember">保存</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="showCreateInvite" title="生成激活码" width="560px" destroy-on-close>
      <el-form :model="inviteForm" label-width="96px" @submit.prevent>
        <el-form-item label="身份">
          <el-select v-model="inviteForm.identity" style="width: 100%">
            <el-option
              v-for="id in MEMBER_IDENTITIES"
              :key="id"
              :value="id"
              :label="MEMBER_IDENTITY_LABELS[id]"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="最大使用次数">
          <el-input-number v-model="inviteForm.maxUses" :min="1" :max="999" />
        </el-form-item>
        <el-form-item label="有效天数">
          <el-input-number v-model="inviteForm.validDays" :min="1" :max="365" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="inviteForm.note" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateInvite = false">取消</el-button>
        <el-button type="primary" :loading="creatingInvite" @click="submitCreateInvite">
          生成
        </el-button>
      </template>
    </el-dialog>
  </div>
  <div v-else-if="loading" class="detail-skeleton">
    <div class="panel detail-skeleton-panel">
      <div class="skeleton skeleton-line detail-skeleton-title"></div>
      <div class="skeleton skeleton-line"></div>
      <div class="skeleton skeleton-line"></div>
    </div>
    <div class="panel detail-skeleton-panel">
      <div class="skeleton skeleton-line detail-skeleton-title"></div>
      <div class="skeleton skeleton-line"></div>
    </div>
  </div>
</template>
<style scoped lang="scss">
.ticket-preview-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.ticket-preview-body {
  display: flex;
  padding: 8px 0 4px;
  justify-content: center;
  overflow: visible;
}
/* 预览按入场券的实际尺寸（组件里 min(560px, 100%)）显示，不再额外放大 */
// 首屏骨架：比赛信息未返回前先占位，避免空白页与布局跳动
.detail-skeleton {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 4px 0 8px;
  &__title {
    width: 240px;
    height: 26px;
    margin-bottom: 4px;
  }
  &__cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
  }
  &__card {
    height: 84px;
    border-radius: var(--radius-md);
  }
}
.page-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 12px;
  row-gap: 10px;
  margin-bottom: 8px;
}
/* 封面上传 */
.cover-field {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}
.cover-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ticket-image-tip {
  margin: 6px 0 0;
  color: var(--color-text-tertiary);
  font-size: 12px;
  line-height: 1.4;
}
.cover-preview {
  display: block;
  width: 100%;
  max-width: 220px;
  height: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
}
.page-title-block {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  flex: 1 1 auto;
  min-width: 0;
}
.page-title-block > .page-title {
  flex: 1 1 auto;
  min-width: 0;
  word-break: break-word;
}
.page-toolbar > .page-title {
  flex: 1 1 auto;
  min-width: 0;
  word-break: break-word;
}
.page-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
  margin-left: auto;
}
.info-card,
.lifecycle-card,
.report-card,
.history-card {
  margin-bottom: 16px;
}
/* 动画结束后交还 transform，保留 card hover */
.detail-page .anim-fade-in-up {
  animation-fill-mode: backwards;
}
.detail-alert {
  margin-bottom: 16px;
}
.mono {
  font-family: Consolas, Menlo, monospace;
  font-size: var(--font-sm);
}
.muted {
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}
.lifecycle-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.lifecycle-step-count {
  font-size: var(--font-xs);
  font-weight: 500;
  color: var(--color-text-tertiary);
}
.lifecycle-steps {
  margin: 4px 0 0;
}
/* 窄屏链条单行横滚，避免标签折行 */
.lifecycle-steps-scroll {
  overflow: hidden;
}
.lifecycle-steps :deep(.el-step__title) {
  font-size: var(--font-sm);
  transition: color var(--dur-base) var(--ease-standard);
}
.lifecycle-steps :deep(.el-step__title.is-success),
.lifecycle-steps :deep(.el-step__title.is-wait) {
  color: var(--color-text-tertiary);
  font-weight: 500;
}
.lifecycle-steps :deep(.el-step__title.is-process) {
  color: var(--color-text-primary);
  font-weight: 700;
}
.lifecycle-steps :deep(.el-step__head.is-success .el-step__icon) {
  /* 底色用不透明底 + 内阴影叠淡绿：避免连接线从半透明圆点里透出来压住对勾 */
  background: var(--color-surface);
  box-shadow: inset 0 0 0 999px var(--color-success-soft);
  border-color: transparent;
  color: var(--color-success);
}
.lifecycle-steps :deep(.el-step__head.is-wait .el-step__icon) {
  color: var(--color-text-tertiary);
  border-color: var(--color-border-strong);
}
.lifecycle-steps :deep(.el-step__head.is-process .el-step__icon) {
  background: var(--gradient-brand);
  border-color: transparent;
  color: var(--color-surface);
  box-shadow: 0 0 0 4px rgba(var(--color-primary-rgb), 0.12);
}
.lifecycle-steps :deep(.el-step__head .el-step__icon) {
  transition:
    background var(--dur-base) var(--ease-standard),
    box-shadow var(--dur-base) var(--ease-standard),
    border-color var(--dur-base) var(--ease-standard);
}
.lifecycle-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}
.quick-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.pkg-upload {
  width: 100%;
}
.import-actions {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
}
.import-file {
  color: var(--color-text-secondary);
  font-size: 13px;
}
.report-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.report-head-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.report-title {
  font-weight: 600;
  color: var(--color-text-primary);
}
.report-head-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.report-meta {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  font-size: var(--font-xs);
}
.report-meta-label {
  color: var(--color-text-tertiary);
}
.report-meta-value {
  color: var(--color-text-secondary);
  font-weight: 500;
}
.report-section + .report-section {
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--color-border);
}
.report-alert {
  margin-bottom: 8px;
}
.report-alert:last-child {
  margin-bottom: 0;
}
.tab-toolbar {
  margin-bottom: 12px;
}
.mini-tag {
  margin: 2px 4px 2px 0;
}
.copy-btn {
  margin-left: 8px;
}
.detail-skeleton {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.detail-skeleton-panel {
  padding: 20px 24px;
  min-height: 132px;
}
.detail-skeleton .detail-skeleton-title {
  width: 32%;
  height: 16px;
  margin-bottom: 18px;
}
.detail-skeleton .detail-skeleton-panel:last-child {
  min-height: 104px;
}
@media (max-width: 640px) {
  .lifecycle-steps-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    padding-bottom: 2px;
  }
  .lifecycle-steps {
    min-width: 540px;
  }
}
</style>