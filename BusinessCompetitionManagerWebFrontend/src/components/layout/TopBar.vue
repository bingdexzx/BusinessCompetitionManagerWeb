<template>
  <div class="topbar">
    <div class="topbar-left">
      <el-button
        v-if="showMenuToggle"
        class="menu-toggle"
        aria-label="打开菜单"
        @click="emit('toggle')"
      >
        <el-icon :size="20"><Menu /></el-icon>
      </el-button>
      <el-breadcrumb separator="/">
        <el-breadcrumb-item :to="{ path: '/competitions' }">商赛辅助办赛系统</el-breadcrumb-item>
        <el-breadcrumb-item v-if="currentPageTitle">{{ currentPageTitle }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <div class="topbar-right">
      <el-select
        class="competition-select"
        :model-value="auth.selectedCompetitionId"
        placeholder="选择比赛"
        filterable
        clearable
        :loading="competitionsLoading"
        @change="onCompetitionChange"
      >
        <el-option v-for="item in competitionOptions" :key="item.id" :label="item.name" :value="item.id" />
      </el-select>

      <el-badge
        :value="unreadCount"
        :hidden="unreadCount === 0"
        :max="99"
        class="notice-bell"
      >
        <el-button class="bell-btn" aria-label="消息中心" @click="goMessages">
          <el-icon :size="18"><Bell /></el-icon>
        </el-button>
      </el-badge>

      <el-dropdown trigger="click" @command="onUserCommand">
        <span class="user-info">
          <span class="user-name">{{ displayName }}</span>
          <el-tag v-if="roleLabel" size="small" :type="roleTagType" class="role-tag">{{
            roleLabel
          }}</el-tag>
          <el-icon class="user-arrow"><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">
              <el-icon><UserFilled /></el-icon>个人档案
            </el-dropdown-item>
            <el-dropdown-item command="password">
              <el-icon><Lock /></el-icon>修改密码
            </el-dropdown-item>
            <el-dropdown-item command="logout" divided>
              <el-icon><SwitchButton /></el-icon>退出登录
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>

      <ChangePasswordDialog v-model="passwordDialogVisible" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import { useNotifications } from '@/composables/useNotifications'
import { errorMessage } from '@/utils/errors'
import { pageTitleOf } from '@/utils/pageTitles'
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue'

const { unreadCount, resetUnread } = useNotifications()

function goMessages(): void {
  resetUnread()
  void router.push({ name: 'messages' })
}

defineProps<{
  /** 平板/手机（抽屉模式）下显示汉堡按钮，由父级 AppLayout 注入 */
  showMenuToggle?: boolean
}>()

const emit = defineEmits<{
  toggle: []
}>()

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const competitionsLoading = ref(false)
const superCompetitions = ref<Array<{ id: number; name: string }>>([])

watch(
  () => auth.isSuperuser,
  async (su) => {
    if (!su) {
      superCompetitions.value = []
      return
    }
    competitionsLoading.value = true
    try {
      superCompetitions.value = (await api.getCompetitions()).map((c) => ({ id: c.id, name: c.name }))
    } catch (err) {
      ElMessage.error(errorMessage(err, '获取比赛列表失败'))
    } finally {
      competitionsLoading.value = false
    }
  },
  { immediate: true },
)

// 选项：我的比赛（memberships）+ 系统超级管理员的全部比赛，去重合并
const competitionOptions = computed(() => {
  const map = new Map<number, string>()
  for (const m of auth.memberships) {
    map.set(m.id, m.competitionName)
  }
  for (const c of superCompetitions.value) {
    if (!map.has(c.id)) map.set(c.id, c.name)
  }
  return [...map].map(([id, name]) => ({ id, name }))
})

/** 切换比赛：更新上下文；若正处于比赛内页面，跳到新比赛的同名模块 */
async function onCompetitionChange(value: number | string | null): Promise<void> {
  auth.selectCompetition(value)
  const cid = value === null || value === '' ? null : String(value)
  const currentCid = route.params.cid
  if (cid && typeof currentCid === 'string' && currentCid) {
    const suffix = route.path.replace(/^\/competitions\/[^/]+/, '')
    await router.push(`/competitions/${cid}${suffix}`)
  }
}

const displayName = computed(
  () => auth.user?.displayName || auth.user?.username || '用户',
)
const roleLabel = computed(() => {
  if (auth.isSuperuser) return '超级管理员'
  return auth.currentIdentityLabel || ''
})
const roleTagType = computed(() => (auth.isSuperuser ? 'danger' : 'primary'))

const passwordDialogVisible = ref(false)

function onUserCommand(command: string | number | object): void {
  if (command === 'profile') {
    void router.push('/profile')
    return
  }
  if (command === 'password') {
    passwordDialogVisible.value = true
    return
  }
  if (command === 'logout') {
    auth.logout()
    void router.push('/login')
  }
}

const currentPageTitle = computed(() =>
  pageTitleOf(route.path, route.query as Record<string, unknown>),
)</script>

<style scoped>
.topbar {
  height: var(--topbar-height);
  background: var(--glass-bg-strong);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--color-border);
  box-shadow:
    0 1px 0 rgba(16, 24, 40, 0.02),
    0 4px 16px rgba(16, 24, 40, 0.04);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--content-padding);
  flex-shrink: 0;
  position: relative;
  z-index: 5;
}
.topbar::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(99, 102, 241, 0.15) 30%,
    rgba(139, 92, 246, 0.15) 70%,
    transparent 100%
  );
  pointer-events: none;
}
.topbar-left {
  display: flex;
  align-items: center;
  min-width: 0;
}
.topbar-right {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 14px;
}
.menu-toggle {
  margin-right: 6px;
  color: var(--color-text-secondary);
  width: 36px !important;
  height: 36px !important;
  padding: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  border: 1px solid var(--color-border, var(--color-border-strong)) !important;
  border-radius: 6px !important;
  background: var(--el-fill-color-blank) !important;
}
.menu-toggle:hover {
  color: var(--color-primary);
  border-color: var(--color-primary, var(--color-primary)) !important;
  background: var(--el-fill-color-light, var(--surface-sunken)) !important;
}
@media (max-width: 1024px) {
  .menu-toggle {
    margin-left: -12px !important;
  }
}
.competition-select {
  width: 200px;
}
@media (max-width: 640px) {
  .competition-select {
    width: 120px;
  }
}
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--color-text-primary);
  min-width: 0;
  cursor: pointer;
  outline: none;
}
.user-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  max-width: 160px;
  font-weight: 500;
}
.role-tag {
  font-size: 11px;
  height: 20px;
  line-height: 18px;
  flex-shrink: 0;
}
.user-arrow {
  color: var(--color-text-tertiary);
  flex-shrink: 0;
}
@media (max-width: 640px) {
  .topbar-left .el-breadcrumb {
    display: none;
  }
}
</style>
