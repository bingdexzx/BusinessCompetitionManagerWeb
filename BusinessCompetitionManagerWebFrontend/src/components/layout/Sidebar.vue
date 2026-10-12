<template>
  <div class="sidebar" :class="{ 'is-drawer': drawer, 'is-open': open }">
    <!-- 品牌区：logo + 渐变标题 + 当前比赛信息（旧产品同款视觉） -->
    <div class="sidebar-brand">
      <div class="brand-text">
        <div class="brand-title-row">
          <img class="brand-logo" src="@/assets/logo.svg" alt="logo" />
          <div class="brand-name">商赛办赛管理系统</div>
        </div>
        <div class="brand-meta">
          <div v-if="competitionName" class="meta-row">
            <el-tag type="success" size="small" effect="plain" class="meta-name">{{
              competitionName
            }}</el-tag>
          </div>
          <div v-else class="meta-row meta-hint">
            未选择比赛 —
            <router-link to="/competitions">比赛列表</router-link>
          </div>
        </div>
      </div>
    </div>

    <el-menu :default-active="activeMenu" router class="sidebar-menu ai-sidebar">
      <!-- 比赛列表 -->
      <el-menu-item index="/competitions">
        <el-icon><Trophy /></el-icon>
        <span>比赛列表</span>
      </el-menu-item>

      <!-- 当前比赛：选中比赛（路由带 :cid 或已选上下文）后展示 -->
      <el-menu-item-group v-if="hasCompetition" title="当前比赛" class="sidebar-group">
        <el-menu-item :index="`/competitions/${activeCid}`">
          <el-icon><InfoFilled /></el-icon>
          <span>比赛详情</span>
        </el-menu-item>
        <el-menu-item :index="`/competitions/${activeCid}/teams`">
          <el-icon><User /></el-icon>
          <span>组队管理</span>
        </el-menu-item>
        <el-menu-item :index="`/competitions/${activeCid}/contracts`">
          <el-icon><Files /></el-icon>
          <span>合同工作台</span>
        </el-menu-item>
        <el-menu-item :index="`/competitions/${activeCid}/fiscal`">
          <el-icon><Calendar /></el-icon>
          <span>财年与补录</span>
        </el-menu-item>
        <el-menu-item v-if="canViewSettlement" :index="`/competitions/${activeCid}/settlement`">
          <el-icon><TrophyBase /></el-icon>
          <span>结算与获奖</span>
        </el-menu-item>
        <el-menu-item :index="`/competitions/${activeCid}/logs`">
          <el-icon><DataLine /></el-icon>
          <span>字段日志</span>
        </el-menu-item>
        <!-- 审计日志：比赛超管/管理员 或 系统超管可见 -->
        <el-menu-item v-if="canViewAudit" :index="`/competitions/${activeCid}/audit`">
          <el-icon><Document /></el-icon>
          <span>审计日志</span>
        </el-menu-item>
      </el-menu-item-group>

      <el-menu-item index="/messages">
        <el-icon><Bell /></el-icon>
        <span>消息中心</span>
      </el-menu-item>

      <el-menu-item index="/profile">
        <el-icon><UserFilled /></el-icon>
        <span>个人档案</span>
      </el-menu-item>

      <!-- 系统：仅系统超管可见 -->
      <el-menu-item-group v-if="auth.isSuperuser" title="系统" class="sidebar-group">
        <el-menu-item index="/logs">
          <el-icon><Monitor /></el-icon>
          <span>网络日志</span>
        </el-menu-item>
        <el-menu-item index="/plugins">
          <el-icon><Box /></el-icon>
          <span>插件管理</span>
        </el-menu-item>
      </el-menu-item-group>
    </el-menu>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  /** 抽屉模式（平板/手机）：由父级 AppLayout 控制显隐 */
  drawer?: boolean
  open?: boolean
}>()

const route = useRoute()
const auth = useAuthStore()

/** 当前比赛 id：路由 /competitions/:cid/... 优先，其次选中的比赛上下文 */
const activeCid = computed(() => {
  const cid = route.params.cid
  if (typeof cid === 'string' && cid) return cid
  return auth.selectedCompetitionId !== null ? String(auth.selectedCompetitionId) : ''
})
const hasCompetition = computed(() => activeCid.value !== '')

/** 本比赛超级管理员 / 系统超管（与后端 can_manage_competition 口径一致） */
const canManageComp = computed(() => {
  if (auth.isSuperuser) return true
  return auth.currentMembership?.identity === 'COMP_SUPER_ADMIN'
})
/** 审计日志可见性：系统超管 / 比赛超管（主席团与参赛代表不可见） */
const canViewAudit = canManageComp
/** 结算与获奖：仅超管可见（决策：结算结果仅超管可见） */
const canViewSettlement = canManageComp

// 当前比赛名（侧栏品牌区展示）：成员身份自带名称，系统超管按需查询
const competitionName = ref('')
watch(
  activeCid,
  async (cid) => {
    if (!cid) {
      competitionName.value = ''
      return
    }
    const fromMembership = auth.currentMembership?.competitionName
    if (fromMembership) {
      competitionName.value = fromMembership
      return
    }
    try {
      competitionName.value = (await api.getCompetition(cid)).name
    } catch {
      competitionName.value = ''
    }
  },
  { immediate: true },
)

// 菜单高亮：合同详情页归入「合同工作台」
const activeMenu = computed(() => {
  const path = route.path
  if (/^\/competitions\/[^/]+\/contracts\/[^/]+$/.test(path)) {
    return `/competitions/${activeCid.value}/contracts`
  }
  return path
})
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-width);
  height: 100vh; /* 回退 */
  height: 100dvh; /* 移动端动态视口高度，避免抽屉下沿被地址栏遮挡 */
  background: linear-gradient(180deg, #ffffff 0%, #fafbfe 100%);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  user-select: none;
  position: relative;
  overflow: hidden;
  z-index: 10;
}
.sidebar::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--gradient-brand);
  z-index: 2;
  pointer-events: none;
}
.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 20px 18px;
  border-bottom: 1px solid var(--color-border);
}
.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
  width: 100%;
}
.brand-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-logo {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(var(--color-primary-rgb), 0.28);
}
.brand-name {
  font-size: 16px;
  font-weight: 800;
  background: var(--gradient-brand);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  letter-spacing: 0.3px;
}
.brand-meta {
  margin-top: 10px;
  padding: 10px;
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: #f7f8fa;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.brand-meta .meta-row {
  display: flex;
  justify-content: center;
}
.brand-meta .meta-name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.brand-meta .meta-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.brand-meta .meta-hint a {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}
.brand-meta .meta-hint a:hover {
  text-decoration: underline;
}
.sidebar-menu {
  flex: 1;
  border-right: none;
  overflow-y: auto;
  padding: 12px 0;
}
.sidebar-menu :deep(.el-menu-item-group__title) {
  padding: 10px 20px 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
}
.sidebar-menu :deep(.el-sub-menu__title),
.sidebar-menu :deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  margin: 2px 12px;
  border-radius: var(--radius-sm);
  font-size: 13.5px;
  color: var(--color-text-secondary);
  transition: all var(--dur-base) var(--ease-out-expo);
  position: relative;
  overflow: hidden;
}
/* Hover: 渐变背景滑入 + 图标微移 */
.sidebar-menu :deep(.el-sub-menu__title:hover),
.sidebar-menu :deep(.el-menu-item:not(.is-active):hover) {
  background: var(--el-color-primary-light-9);
  color: var(--color-primary);
  transform: translateX(2px);
}
.sidebar-menu :deep(.el-menu-item.is-active) {
  position: relative;
  background: var(--gradient-brand-soft);
  color: var(--color-primary);
  font-weight: 600;
  transform: translateX(2px);
}
.sidebar-menu :deep(.el-menu-item.is-active)::before {
  content: "";
  position: absolute;
  left: -12px;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 22px;
  border-radius: 0 4px 4px 0;
  background: var(--gradient-brand);
}
.sidebar-menu :deep(.el-sub-menu__title) {
  font-weight: 500;
}
.sidebar-menu :deep(.el-menu-item .el-icon),
.sidebar-menu :deep(.el-sub-menu__title .el-icon) {
  font-size: 17px;
}

/* ===== 抽屉模式（平板/手机）：固定浮层 + 滑入动画，桌面模式不受影响 ===== */
.sidebar.is-drawer {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 60;
  max-width: 320px;
  transform: translateX(-100%);
  transition: transform var(--dur-base) var(--ease-out-expo);
  box-shadow: var(--shadow-xl);
}
.sidebar.is-drawer.is-open {
  transform: translateX(0);
}
</style>
