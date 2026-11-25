<script setup lang="ts">
// 账号管理（仅系统超级管理员）：分页表格 + 搜索 + 新建/编辑 + 重置密码 + 删除 + 启用/停用
// 接口契约见 src/api/userAdminApi.ts；错误提示统一展示后端中文 message
import { onMounted, reactive, ref } from 'vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { createSchool, getSchools } from '@/api'
import {
  createUser,
  deleteUser,
  getUsers,
  resetUserPassword,
  updateUser,
} from '@/api/userAdminApi'
import type { UserAdminItem, UserMembershipSummary } from '@/api/userAdminApi'
import type { School } from '@/api/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'
import { useResourceRefresh } from '@/composables/useNotifications'
const PAGE_SIZE = 20
// ---------- 列表 ----------
const items = ref<UserAdminItem[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
const keyword = ref('')
async function loadUsers(): Promise<void> {
  loading.value = true
  try {
    const res = await getUsers({
      page: page.value,
      pageSize: PAGE_SIZE,
      q: keyword.value.trim() || undefined,
    })
    items.value = res.items ?? []
    total.value = res.total ?? 0
  } catch (err) {
    ElMessage.error(errorMessage(err, '加载账号列表失败'))
  } finally {
    loading.value = false;
  hasLoaded.value = true;
  }
}
// 实时刷新：账号 / 学校 / 比赛成员身份 变更广播（400ms 去抖合并）后重拉当前页，保留页码与搜索词
useResourceRefresh(['users', 'schools', 'members'], loadUsers)
function search(): void {
  page.value = 1
  void loadUsers()
}
// ---------- 学校选择（远程搜索） ----------
const schoolOptions = ref<School[]>([])
const schoolLoading = ref(false)
async function searchSchools(q: string): Promise<void> {
  schoolLoading.value = true
  try {
    schoolOptions.value = await getSchools(q || undefined)
  } catch {
    schoolOptions.value = []
  } finally {
    schoolLoading.value = false
  }
}
/** 就地新增学校（系统超级管理员）：建好后自动选中，省去切到「学校管理」页再回来 */
async function createSchoolInline(): Promise<void> {
  let name = ''
  try {
    const { value } = await ElMessageBox.prompt('请输入学校名称', '新增学校', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputPlaceholder: '学校名称（唯一）',
      inputValidator: (v: string) => (v && v.trim() ? true : '请输入学校名称'),
    })
    name = String(value || '').trim()
  } catch {
    return // 用户取消
  }
  if (!name) return
  try {
    const created = await createSchool({ name })
    schoolOptions.value = [created, ...schoolOptions.value.filter((s) => s.id !== created.id)]
    form.schoolId = created.id
    ElMessage.success('学校已新增并选中')
  } catch (err) {
    ElMessage.error(errorMessage(err, '新增学校失败'))
  }
}
// ---------- 新建 / 编辑 ----------
const dialogVisible = ref(false)
const dialogSaving = ref(false)
const editingId = ref<number | null>(null)
const editingMemberships = ref<UserMembershipSummary[]>([])
const formRef = ref<FormInstance>()
const form = reactive({
  username: '',
  password: '',
  displayName: '',
  email: '',
  schoolId: null as number | null,
  isSuperuser: false,
  isActive: true,
})
const createRules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { max: 150, message: '用户名最长 150 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度需为 8-64 位', trigger: 'blur' },
  ],
  displayName: [
    { required: true, message: '请输入显示名', trigger: 'blur' },
    { max: 100, message: '显示名最长 100 个字符', trigger: 'blur' },
  ],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}
const editRules: FormRules = {
  displayName: createRules.displayName,
  email: createRules.email,
}
const IDENTITY_LABELS: Record<string, string> = {
  ADMIN: '管理员（主席团）',
  PLAYER: '参赛代表',
}
function identityLabel(identity: string): string {
  return IDENTITY_LABELS[identity] ?? identity
}
function resetForm(): void {
  form.username = ''
  form.password = ''
  form.displayName = ''
  form.email = ''
  form.schoolId = null
  form.isSuperuser = false
  form.isActive = true
}
function openCreate(): void {
  editingId.value = null
  editingMemberships.value = []
  resetForm()
  dialogVisible.value = true
  void searchSchools('')
  formRef.value?.clearValidate()
}
function openEdit(row: UserAdminItem): void {
  editingId.value = row.id
  editingMemberships.value = row.memberships ?? []
  resetForm()
  form.username = row.username
  form.displayName = row.displayName
  form.email = row.email ?? ''
  form.schoolId = row.school?.id ?? null
  form.isSuperuser = row.isSuperuser
  form.isActive = row.isActive
  dialogVisible.value = true
  void searchSchools('')
  formRef.value?.clearValidate()
}
async function submit(): Promise<void> {
  const formEl = formRef.value
  if (!formEl) return
  try {
    await formEl.validate()
  } catch {
    return
  }
  dialogSaving.value = true
  try {
    if (editingId.value === null) {
      await createUser({
        username: form.username.trim(),
        password: form.password,
        displayName: form.displayName.trim(),
        email: form.email.trim() || undefined,
        schoolId: form.schoolId ?? undefined,
        isSuperuser: form.isSuperuser,
      })
      ElMessage.success('账号已创建')
    } else {
      await updateUser(editingId.value, {
        displayName: form.displayName.trim(),
        email: form.email.trim() || null,
        schoolId: form.schoolId ?? null,
        isActive: form.isActive,
        isSuperuser: form.isSuperuser,
      })
      ElMessage.success('账号已更新')
    }
    dialogVisible.value = false
    await loadUsers()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    dialogSaving.value = false
  }
}
// ---------- 重置密码 ----------
const pwdVisible = ref(false)
const pwdSaving = ref(false)
const pwdTarget = ref<UserAdminItem | null>(null)
const pwdFormRef = ref<FormInstance>()
const pwdForm = reactive({ password: '' })
const pwdRules: FormRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度需为 8-64 位', trigger: 'blur' },
  ],
}
function openReset(row: UserAdminItem): void {
  pwdTarget.value = row
  pwdForm.password = ''
  pwdVisible.value = true
  pwdFormRef.value?.clearValidate()
}
async function submitPassword(): Promise<void> {
  const formEl = pwdFormRef.value
  const target = pwdTarget.value
  if (!formEl || !target) return
  try {
    await formEl.validate()
  } catch {
    return
  }
  pwdSaving.value = true
  try {
    await resetUserPassword(target.id, pwdForm.password)
    ElMessage.success('密码已重置，该账号已登录的会话已全部失效')
    pwdVisible.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err, '重置密码失败'))
  } finally {
    pwdSaving.value = false
  }
}
// ---------- 删除 ----------
async function removeUser(row: UserAdminItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除账号「${row.displayName || row.username}」？删除后不可恢复。`,
      '删除账号',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await deleteUser(row.id)
    ElMessage.success('账号已删除')
    await loadUsers()
  } catch (err) {
    // 后端拒绝时展示中文提示（不能删除自己 / 不能删除最后一个系统超级管理员）
    ElMessage.error(errorMessage(err, '删除失败'))
  }
}
// ---------- 启用 / 停用 ----------
async function toggleActive(row: UserAdminItem, val: unknown): Promise<void> {
  const next = val === true
  try {
    await updateUser(row.id, { isActive: next })
    row.isActive = next
    ElMessage.success(next ? '已启用' : '已停用')
  } catch (err) {
    row.isActive = !next // 失败回滚开关
    ElMessage.error(errorMessage(err, '操作失败'))
  }
}
onMounted(() => void loadUsers())
</script>
<template>
  <div class="user-admin-view page">
    <PageHeader title="账号管理" />
    <el-card shadow="never" class="table-card anim-fade-in-up">
      <div class="filter-bar">
        <el-input
          v-model="keyword"
          placeholder="用户名 / 显示名 / 邮箱"
          clearable
          style="width: 240px"
          @keyup.enter="search"
          @clear="search"
        />
        <el-button type="primary" :icon="Search" @click="search">查询</el-button>
        <el-button type="success" :icon="Plus" @click="openCreate">新建账号</el-button>
        <el-button :icon="Refresh" @click="loadUsers">刷新</el-button>
      </div>
            <TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
<el-table :data="items" v-loading="loading && hasLoaded" stripe size="small" border class="table--sticky-head" max-height="calc(100vh - 320px)">
        <el-table-column label="用户名" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.username }}</template>
        </el-table-column>
        <el-table-column label="显示名" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.displayName || '—' }}</template>
        </el-table-column>
        <el-table-column label="邮箱" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.email || '—' }}</template>
        </el-table-column>
        <el-table-column label="学校" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.school?.name || '—' }}</template>
        </el-table-column>
        <el-table-column label="超级管理员" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.isSuperuser" type="danger" size="small" effect="plain">超级管理员</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="row.isActive"
              active-text="启用"
              inactive-text="停用"
              inline-prompt
              @change="(val: boolean | string | number) => toggleActive(row, val)"
            />
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.createdAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)" size="small">编辑</el-button>
            <el-button link type="danger" class="op-muted" @click="openReset(row)" size="small">
              重置密码
            </el-button>
            <el-button link type="danger" class="op-danger" @click="removeUser(row)" size="small">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无账号数据" :image-size="72" />
        </template>
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="PAGE_SIZE"
          :total="total"
          layout="total, prev, pager, next"
          background
          @current-change="loadUsers"
        />
      </div>
    </el-card>
    <!-- ===== 新建 / 编辑账号 ===== -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建账号' : '编辑账号'"
      width="560px"
      destroy-on-close
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="editingId === null ? createRules : editRules"
        label-width="96px"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="form.username"
            :disabled="editingId !== null"
            maxlength="150"
            placeholder="登录用户名（唯一）"
          />
        </el-form-item>
        <el-form-item v-if="editingId === null" label="初始密码" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            maxlength="128"
            placeholder="8-128 位"
          />
        </el-form-item>
        <el-form-item label="显示名" prop="displayName">
          <el-input v-model="form.displayName" maxlength="100" placeholder="真实姓名 / 昵称" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" maxlength="254" placeholder="可选（唯一）" />
        </el-form-item>
        <el-form-item label="学校" prop="schoolId">
          <div class="school-picker">
            <el-select
              v-model="form.schoolId"
              filterable
              remote
              clearable
              placeholder="搜索学校（可留空）"
              :remote-method="searchSchools"
              :loading="schoolLoading"
            >
              <el-option v-for="s in schoolOptions" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-button :icon="Plus" @click="createSchoolInline">新增学校</el-button>
          </div>
        </el-form-item>
        <el-form-item label="超级管理员">
          <el-switch v-model="form.isSuperuser" />
          <span class="hint">开启后可维护账号、比赛与系统配置</span>
        </el-form-item>
        <el-form-item v-if="editingId !== null" label="启用状态">
          <el-switch v-model="form.isActive" />
          <span class="hint">停用后该账号无法登录</span>
        </el-form-item>
        <el-form-item v-if="editingId !== null" label="比赛身份">
          <div class="membership-list">
            <el-tag
              v-for="m in editingMemberships"
              :key="m.competitionId"
              size="small"
              type="info"
              class="membership-tag"
            >
              #{{ m.competitionId }} · {{ identityLabel(m.identity)
              }}{{ m.managedCompanies.length ? `（所辖公司 ${m.managedCompanies.length}）` : '' }}
            </el-tag>
            <span v-if="!editingMemberships.length" class="hint">暂无比赛身份</span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dialogSaving" @click="submit">
          {{ editingId === null ? '创建' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
    <!-- ===== 重置密码 ===== -->
    <el-dialog v-model="pwdVisible" title="重置密码" width="420px" destroy-on-close>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="重置后该账号已登录的会话将全部失效（顶号），需用新密码重新登录。"
        class="pwd-tip"
      />
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="96px">
        <el-form-item label="账号">
          <span>{{ pwdTarget ? `${pwdTarget.displayName || pwdTarget.username}（${pwdTarget.username}）` : '—' }}</span>
        </el-form-item>
        <el-form-item label="新密码" prop="password">
          <el-input
            v-model="pwdForm.password"
            type="password"
            show-password
            maxlength="128"
            placeholder="8-128 位"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="submitPassword">重置</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.user-admin-view {
  display: flex;
  flex-direction: column;
}
.table-card {
  margin-bottom: 16px;
}
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.muted {
  color: var(--color-text-tertiary);
}
/* 操作列权重：编辑最重；重置密码/删除平时弱化，悬停才显色（危险操作视觉降级） */
:deep(.op-muted.el-button.is-link) {
  color: var(--color-text-tertiary);
}
:deep(.op-muted.el-button.is-link:hover) {
  color: var(--color-warning);
}
:deep(.op-danger.el-button.is-link) {
  color: var(--color-text-tertiary);
}
:deep(.op-danger.el-button.is-link:hover) {
  color: var(--color-danger);
}
.hint {
  margin-left: 10px;
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
}
.membership-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
/* 学校选择 + 就地新增学校 */
.school-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.school-picker :deep(.el-select) {
  flex: 1;
  min-width: 0;
}
.membership-tag {
  margin-right: 0;
}
.pwd-tip {
  margin-bottom: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>