<script setup lang="ts">
// 比赛详情页：基本信息 / 生命周期推进 / 比赛包导入 / 成员管理 / 激活码 / 快捷入口
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules, UploadFile } from 'element-plus'
import * as api from '@/api'
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
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()
const router = useRouter()
const auth = useAuthStore()

const competition = ref<Competition | null>(null)
const loading = ref(false)
const activeTab = ref('package')

// ---------- 权限 ----------
/** 系统超管或本比赛超管：可编辑信息 / 推进生命周期 / 激活码 */
const canManage = computed(() => {
  if (auth.isSuperuser) return true
  return auth.memberships.some(
    (m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN',
  )
})
const isSystemAdmin = computed(() => auth.isSuperuser)

// ---------- 生命周期 ----------
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
function statusText(status: string): string {
  return STATUS_LABELS[status] ?? status
}
/** 状态标签配色 */
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

/** 各状态下一步的推进动作 */
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
    label: '结算完成关闭',
    confirmText: '确认结算完成并关闭比赛？关闭后不可再推进。',
  },
}
const nextAction = computed(() => {
  const status = competition.value?.status ?? ''
  return NEXT_ACTIONS[status]
})

async function doTransition(action: NextAction): Promise<void> {
  try {
    await ElMessageBox.confirm(action.confirmText, '生命周期推进', {
      type: 'warning',
      confirmButtonText: '确认',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    competition.value = await api.transitionCompetition(props.cid, action.target)
    ElMessage.success(`已推进至「${statusText(action.target)}」`)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}

// ---------- 编辑比赛信息 ----------
const showEdit = ref(false)
const editing = ref(false)
const editRef = ref<FormInstance>()
const editForm = ref({
  name: '',
  code: '',
  coverImage: '',
  hostSchoolId: null as number | null,
  location: '',
  staffingInfo: '',
})
const editRules: FormRules = {
  name: [{ required: true, message: '请填写比赛名称', trigger: 'blur' }],
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
    hostSchoolId: comp.hostSchoolId,
    location: comp.location,
    staffingInfo: comp.staffingInfo,
  }
  showEdit.value = true
  // 加载学校下拉选项
  schoolsLoading.value = true
  try {
    schools.value = await api.getSchools()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
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
      coverImage: editForm.value.coverImage.trim() || undefined,
      hostSchoolId: editForm.value.hostSchoolId ?? undefined,
      location: editForm.value.location.trim() || undefined,
      staffingInfo: editForm.value.staffingInfo.trim() || undefined,
    })
    ElMessage.success('比赛信息已更新')
    showEdit.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    editing.value = false
  }
}

// ---------- 比赛包导入 ----------
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

/** limit=1 时再选文件触发的是 on-exceed（不是 on-change）：这里直接替换为新文件 */
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

async function doImport(): Promise<void> {
  const file = uploadFile.value
  if (!file) {
    ElMessage.warning('请先选择比赛包 .zip 文件')
    return
  }
  importing.value = true
  try {
    const record = await api.importCompetitionPackage(props.cid, file)
    activeReport.value = record.report
    if (record.status === 'SUCCESS') {
      ElMessage.success('比赛包导入成功')
      // 导入成功后比赛库就绪，刷新状态
      await Promise.all([loadCompetition(), loadPackages()])
    } else {
      ElMessage.error('比赛包导入失败，请查看导入报告')
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
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    packagesLoading.value = false
  }
}

/** 基础数据行数（key -> 行数）转表格数据 */
const basedataEntries = computed(() => {
  const rows = activeReport.value?.basedataRows ?? {}
  return Object.entries(rows).map(([key, count]) => ({ key, count }))
})

function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 12) : '—'
}

// ---------- 成员管理（系统超管） ----------
const members = ref<CompetitionMember[]>([])
const membersLoading = ref(false)

// 指派成员弹窗
const showAssign = ref(false)
const assigning = ref(false)
const assignForm = ref({
  username: '',
  identity: 'PLAYER' as MemberIdentity,
  managedCompanies: '',
})

// 编辑成员弹窗
const showEditMember = ref(false)
const editingMember = ref(false)
const editMemberTarget = ref<CompetitionMember | null>(null)
const editMemberForm = ref({
  identity: 'PLAYER' as MemberIdentity,
  managedCompanies: '',
  isActive: true,
})

/** "1, 2, 3" -> [1, 2, 3] */
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
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    membersLoading.value = false
  }
}

async function submitAssign(): Promise<void> {
  const username = assignForm.value.username.trim()
  if (!username) {
    ElMessage.warning('请填写用户名')
    return
  }
  assigning.value = true
  try {
    await api.assignCompetitionMember(props.cid, {
      username,
      identity: assignForm.value.identity,
      managedCompanies: parseCompanies(assignForm.value.managedCompanies),
    })
    ElMessage.success('成员指派成功')
    showAssign.value = false
    await loadMembers()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    assigning.value = false
  }
}

function openEditMember(row: CompetitionMember): void {
  editMemberTarget.value = row
  editMemberForm.value = {
    identity: row.identity as MemberIdentity,
    managedCompanies: row.managedCompanies.join(', '),
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
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    editingMember.value = false
  }
}

// ---------- 激活码 ----------
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
    ElMessage.error(errorMessage(err, '操作失败'))
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
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    creatingInvite.value = false
  }
}

/** 复制文本到剪贴板 */
async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

// ---------- 快捷入口 ----------
function quickLink(path: string): void {
  void router.push(`/competitions/${props.cid}${path}`)
}

// ---------- 数据加载 ----------
const missing = ref(false)

async function loadCompetition(): Promise<void> {
  loading.value = true
  try {
    competition.value = await api.getCompetition(props.cid)
    missing.value = false
    auth.selectCompetition(props.cid)
  } catch (err) {
    // 404 = 比赛不存在/已删除（旧链接/被清理）：友好状态而非错误弹窗
    if (err instanceof ApiError && err.status === 404) {
      missing.value = true
      competition.value = null
      return
    }
    ElMessage.error(errorMessage(err, '操作失败'))
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

onMounted(() => {
  void loadCompetition()
  void loadPackages()
  if (isSystemAdmin.value) void loadMembers()
  if (canManage.value) void loadInvites()
})
</script>

<template>
  <!-- 比赛不存在/已删除（旧链接残留） -->
  <el-alert
    v-if="missing"
    type="warning"
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

  <div v-if="competition" class="detail-page">
    <!-- ===== 顶部：标题 + 基本信息 ===== -->
    <div class="page-toolbar">
      <h2 class="page-title">{{ competition.name }}</h2>
      <div class="page-actions">
        <el-button v-if="canManage" @click="openEdit">
          <el-icon><Edit /></el-icon>
          <span>编辑信息</span>
        </el-button>
      </div>
    </div>

    <el-card class="info-card" shadow="never">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="比赛编码">
          <span class="mono">{{ competition.code || '—' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusTagType(competition.status)">{{ competition.statusLabel }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="地点">{{ competition.location || '—' }}</el-descriptions-item>
        <el-descriptions-item label="办赛学校">
          {{ competition.hostSchoolName || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="人员安排" :span="2">
          {{ competition.staffingInfo || '—' }}
        </el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">
          {{ formatDateTime(competition.createdAt) }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- ===== 生命周期推进 ===== -->
    <el-card class="lifecycle-card" shadow="never">
      <template #header>生命周期</template>
      <el-steps :active="statusIndex" align-center finish-status="success">
        <el-step v-for="s in statusChain" :key="s" :title="statusText(s)" />
      </el-steps>
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

    <!-- ===== 快捷入口 ===== -->
    <div class="quick-links">
      <el-button @click="quickLink('/teams')">
        <el-icon><User /></el-icon><span>组队管理</span>
      </el-button>
      <el-button @click="quickLink('/contracts')">
        <el-icon><Tickets /></el-icon><span>合同工作台</span>
      </el-button>
      <el-button @click="quickLink('/fiscal')">
        <el-icon><Calendar /></el-icon><span>财年</span>
      </el-button>
      <el-button @click="quickLink('/settlement')">
        <el-icon><DataAnalysis /></el-icon><span>结算</span>
      </el-button>
      <el-button @click="quickLink('/logs')">
        <el-icon><Document /></el-icon><span>字段日志</span>
      </el-button>
    </div>

    <!-- ===== 功能分区 ===== -->
    <el-tabs v-model="activeTab" class="detail-tabs">
      <!-- a) 比赛包导入 -->
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
            <span v-if="uploadFile" class="import-file">{{ uploadFile.name }}</span>
          </div>
        </el-card>

        <!-- 导入报告可视化 -->
        <el-card v-if="activeReport" shadow="never" class="report-card">
          <template #header>
            <div class="report-head">
              <span>导入报告</span>
              <el-tag :type="activeReport.status === 'SUCCESS' ? 'success' : 'danger'" size="small">
                {{ activeReport.status === 'SUCCESS' ? '导入成功' : '导入失败' }}
              </el-tag>
              <span class="muted">建库：{{ activeReport.createdDatabase || '未创建数据库' }}</span>
              <span class="muted">合同实例：{{ activeReport.contractsCreated ?? 0 }}</span>
            </div>
          </template>

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

          <h4 class="report-section-title">插件（{{ activeReport.plugins?.length ?? 0 }}）</h4>
          <el-table :data="activeReport.plugins" size="small" border>
            <el-table-column prop="file" label="文件" min-width="140" />
            <el-table-column prop="key" label="Key" min-width="110" />
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.kind === 'CONTRACT' ? 'primary' : 'success'">
                  {{ row.kind }}
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

          <h4 class="report-section-title">
            字段迁移（{{ activeReport.fieldMigrations?.length ?? 0 }}）
          </h4>
          <el-table :data="activeReport.fieldMigrations" size="small" border>
            <el-table-column prop="industryKey" label="产业类型" min-width="120" />
            <el-table-column label="新增字段" width="100">
              <template #default="{ row }">+{{ row.added }}</template>
            </el-table-column>
            <el-table-column label="更新字段" width="100">
              <template #default="{ row }">~{{ row.updated }}</template>
            </el-table-column>
            <el-table-column prop="total" label="字段总数" width="100" />
          </el-table>

          <h4 class="report-section-title">基础数据导入</h4>
          <el-table :data="basedataEntries" size="small" border>
            <el-table-column prop="key" label="数据表" min-width="140" />
            <el-table-column prop="count" label="导入行数" width="120" />
          </el-table>
        </el-card>

        <!-- 导入历史 -->
        <el-card shadow="never" class="history-card">
          <template #header>导入历史</template>
          <el-table
            v-loading="packagesLoading"
            :data="packages"
            size="small"
            border
            empty-text="暂无导入记录"
          >
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

      <!-- b) 成员管理（系统超管） -->
      <el-tab-pane v-if="isSystemAdmin" label="成员管理" name="members">
        <el-card shadow="never">
          <div class="tab-toolbar">
            <el-button type="primary" @click="showAssign = true">
              <el-icon><Plus /></el-icon><span>指派成员</span>
            </el-button>
          </div>
          <el-table v-loading="membersLoading" :data="members" border empty-text="暂无成员">
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

      <!-- c) 激活码 -->
      <el-tab-pane v-if="canManage" label="激活码" name="invites">
        <el-card shadow="never">
          <div class="tab-toolbar">
            <el-button type="primary" @click="showCreateInvite = true">
              <el-icon><Plus /></el-icon><span>生成激活码</span>
            </el-button>
          </div>
          <el-table v-loading="invitesLoading" :data="invites" border empty-text="暂无激活码">
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
    </el-tabs>

    <!-- ===== 编辑比赛信息弹窗 ===== -->
    <el-dialog v-model="showEdit" title="编辑比赛信息" width="560px" destroy-on-close>
      <el-form ref="editRef" :model="editForm" :rules="editRules" label-width="96px" @submit.prevent>
        <el-form-item label="比赛名称" prop="name">
          <el-input v-model="editForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="比赛编码">
          <el-input v-model="editForm.code" />
        </el-form-item>
        <el-form-item label="封面图 URL">
          <el-input v-model="editForm.coverImage" placeholder="https://…" />
        </el-form-item>
        <el-form-item label="办赛学校">
          <el-select
            v-model="editForm.hostSchoolId"
            :loading="schoolsLoading"
            filterable
            clearable
            placeholder="输入搜索学校"
            style="width: 100%"
          >
            <el-option v-for="s in schools" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="地点">
          <el-input v-model="editForm.location" />
        </el-form-item>
        <el-form-item label="人员安排">
          <el-input v-model="editForm.staffingInfo" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- ===== 指派成员弹窗 ===== -->
    <el-dialog v-model="showAssign" title="指派成员" width="460px" destroy-on-close>
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

    <!-- ===== 编辑成员弹窗 ===== -->
    <el-dialog v-model="showEditMember" title="编辑成员" width="460px" destroy-on-close>
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

    <!-- ===== 生成激活码弹窗 ===== -->
    <el-dialog v-model="showCreateInvite" title="生成激活码" width="460px" destroy-on-close>
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

  <!-- 加载中占位 -->
  <div v-else v-loading="loading" class="detail-loading"></div>
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
  flex-shrink: 0;
}

.info-card,
.lifecycle-card,
.report-card,
.history-card {
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
  gap: 12px;
  flex-wrap: wrap;
}

.report-alert {
  margin-bottom: 8px;
}

.report-section-title {
  margin: 16px 0 8px;
  font-size: var(--font-base);
  font-weight: 600;
  color: var(--color-text-primary);
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

.detail-loading {
  min-height: 320px;
}
</style>
