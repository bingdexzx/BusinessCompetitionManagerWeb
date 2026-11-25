<template>
  <div class="sidebar" :class="{ 'is-drawer': drawer, 'is-open': open }">
    <div class="sidebar-brand">
      <div class="brand-text">
        <div class="brand-title-row">
          <img class="brand-logo" src="@/assets/logo.svg" alt="logo" />
          <div class="brand-name">商赛辅助办赛系统</div>
        </div>
        <div class="brand-meta">
          <!-- 会话恢复中：不要先闪一句「未选择比赛」 -->
          <div v-if="auth.booting" class="meta-row">
            <div class="skeleton skeleton-line meta-skeleton" />
          </div>
          <div v-else-if="competitionName" class="meta-row">
            <el-tag type="primary" size="small" effect="plain" class="meta-name">{{
              competitionName
            }}</el-tag>
          </div>
          <div v-if="!auth.booting && competitionName && activeCid" class="meta-row meta-fy">
            <FiscalYearBadge :cid="activeCid" />
          </div>
          <div v-else class="meta-row meta-hint">
            未选择比赛 —
            <router-link to="/competitions">比赛列表</router-link>
          </div>
        </div>
      </div>
    </div>

    <el-menu
      ref="menuRef"
      :default-active="activeMenu"
      :default-openeds="defaultOpeneds"
      router
      class="sidebar-menu ai-sidebar"
    >
      <el-menu-item index="/competitions">
        <el-icon><Trophy /></el-icon>
        <span>比赛列表</span>
      </el-menu-item>

      <el-menu-item-group v-if="hasCompetition" title="当前比赛" class="sidebar-group">
        <el-menu-item v-if="auth.isSuperuser" :index="`/competitions/${activeCid}`">
          <el-icon><InfoFilled /></el-icon>
          <span>比赛详情</span>
        </el-menu-item>
        <el-menu-item :index="`/competitions/${activeCid}/dashboard`">
          <el-icon><Odometer /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item :index="`/competitions/${activeCid}/teams`">
          <el-icon><User /></el-icon>
          <span>组队管理</span>
        </el-menu-item>
        <el-menu-item
          v-if="canManageComp"
          :index="`/competitions/${activeCid}/companies`"
        >
          <el-icon><OfficeBuilding /></el-icon>
          <span>公司管理</span>
        </el-menu-item>
        <el-menu-item
          v-if="can('view.contracts')"
          :index="`/competitions/${activeCid}/contracts`"
        >
          <el-icon><Files /></el-icon>
          <span>合同工作台</span>
        </el-menu-item>
        <el-sub-menu index="data-management" class="sidebar-group">
          <template #title>
            <el-icon><Grid /></el-icon>
            <span>数据管理</span>
          </template>
          <el-menu-item
            v-for="item in dataManagementItems"
            :key="item.type"
            :index="`/competitions/${activeCid}/basedata?type=${item.type}`"
          >{{ item.label }}</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="tools-group" class="sidebar-group">
          <template #title>
            <el-icon><Box /></el-icon>
            <span>工具箱</span>
          </template>
          <el-menu-item :index="`/competitions/${activeCid}/tools/material-price`"
            >原料价格</el-menu-item
          >
          <el-menu-item :index="`/competitions/${activeCid}/tools/part-materials`"
            >零件用量</el-menu-item
          >
          <el-menu-item :index="`/competitions/${activeCid}/tools/product-parts`"
            >产品用量</el-menu-item
          >
          <el-menu-item :index="`/competitions/${activeCid}/tools/navigation`"
            >地图导航</el-menu-item
          >
          <el-menu-item :index="`/competitions/${activeCid}/tools/timers`"
            >计时器</el-menu-item
          >
        </el-sub-menu>
        <el-menu-item :index="`/competitions/${activeCid}/region-overview`">
          <el-icon><MapLocation /></el-icon>
          <span>区域总览</span>
        </el-menu-item>
        <el-sub-menu index="stocks-group" class="sidebar-group">
          <template #title>
            <el-icon><TrendCharts /></el-icon>
            <span>股票市场</span>
          </template>
          <el-menu-item :index="`/competitions/${activeCid}/stocks`">股票行情</el-menu-item>
          <el-menu-item :index="`/competitions/${activeCid}/stocks/manage`">交易管理</el-menu-item>
          <el-menu-item
            v-if="canManageComp"
            :index="`/competitions/${activeCid}/stocks/admin`"
          >股票管理</el-menu-item>
        </el-sub-menu>
        <el-menu-item :index="`/competitions/${activeCid}/fiscal`">
          <el-icon><Calendar /></el-icon>
          <span>财年管理</span>
        </el-menu-item>
        <el-menu-item v-if="canViewSettlement" :index="`/competitions/${activeCid}/settlement`">
          <el-icon><TrophyBase /></el-icon>
          <span>结算管理</span>
        </el-menu-item>
        <el-menu-item v-if="canViewFieldLogs" :index="`/competitions/${activeCid}/logs`">
          <el-icon><DataLine /></el-icon>
          <span>字段日志</span>
        </el-menu-item>
        <el-menu-item v-if="canViewAudit" :index="`/competitions/${activeCid}/audit`">
          <el-icon><Document /></el-icon>
          <span>审计流水</span>
        </el-menu-item>
        <el-menu-item v-if="canManageComp" :index="`/competitions/${activeCid}/plugins`">
          <el-icon><Box /></el-icon>
          <span>插件管理</span>
        </el-menu-item>
      </el-menu-item-group>

      <el-menu-item-group title="个人中心" class="sidebar-group">
        <el-menu-item index="/messages">
          <el-icon><Bell /></el-icon>
          <span>消息中心</span>
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><UserFilled /></el-icon>
          <span>个人档案</span>
        </el-menu-item>
      </el-menu-item-group>

      <el-menu-item-group v-if="auth.isSuperuser" title="系统" class="sidebar-group">
        <el-menu-item index="/logs">
          <el-icon><Monitor /></el-icon>
          <span>网络日志</span>
        </el-menu-item>
        <el-menu-item index="/update-logs">
          <el-icon><Notebook /></el-icon>
          <span>更新日志</span>
        </el-menu-item>
        <el-menu-item index="/users">
          <el-icon><User /></el-icon>
          <span>账号管理</span>
        </el-menu-item>
        <el-menu-item index="/schools">
          <el-icon><School /></el-icon>
          <span>学校管理</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu-item-group>
    </el-menu>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as api from '@/api'
import { getCompetitionPermissions } from '@/api'
import { useAuthStore } from '@/stores/auth'
import FiscalYearBadge from '@/components/common/FiscalYearBadge.vue'

defineProps<{
  drawer?: boolean
  open?: boolean
}>()

const route = useRoute()
const auth = useAuthStore()

type MenuHandle = { open?: (index: string) => void }
const menuRef = ref<MenuHandle | null>(null)

/** 数据管理的子菜单项（与 DataManagementView 的子模块一一对应） */
const dataManagementItems = [
  { type: 'materials', label: '原料' },
  { type: 'parts', label: '零件' },
  { type: 'products', label: '产品' },
  { type: 'maps', label: '地图' },
  { type: 'infrastructures', label: '基建' },
  { type: 'tech-tree', label: '科技树' },
  { type: 'fuels', label: '燃料' },
  { type: 'vehicles', label: '载具' },
  { type: 'warehouses', label: '仓库' },
  { type: 'production-lines', label: '生产线' },
]

/** 当前比赛 id：路由 /competitions/:cid/... 优先，其次选中的比赛上下文 */
const activeCid = computed(() => {
  const cid = route.params.cid
  if (typeof cid === 'string' && cid) return cid
  return auth.selectedCompetitionId !== null ? String(auth.selectedCompetitionId) : ''
})

/** 当前比赛的角色权限矩阵（超管恒为全开）：用来隐藏没有权限的菜单入口 */
const permissions = ref<Record<string, string[]> | null>(null)

async function loadPermissions(): Promise<void> {
  if (!activeCid.value || !auth.isAuthenticated) {
    permissions.value = null
    return
  }
  try {
    const data = await getCompetitionPermissions(activeCid.value)
    permissions.value = data.matrix
  } catch {
    permissions.value = null
  }
}

function can(capability: string): boolean {
  if (auth.isSuperuser) return true
  const role = auth.currentMembership?.identity
  if (!permissions.value || !role) return true // 拿不到矩阵时不隐藏，避免误伤
  return (permissions.value[role] ?? []).includes(capability)
}

watch(
  [activeCid, () => auth.currentMembership],
  () => {
    void loadPermissions()
  },
  { immediate: true },
)
const hasCompetition = computed(() => activeCid.value !== '')

/** 本比赛超级管理员 / 系统超级管理员（与后端 can_manage_competition 口径一致） */
const canManageComp = computed(() => auth.isSuperuser)
/** 审计流水可见性：系统超级管理员 / 比赛超级管理员（参赛代表不可见） */
const canViewAudit = canManageComp
const canViewSettlement = canManageComp
/** 字段日志同理：字段级流水含各公司成本/利润，参赛代表一律不可见 */
const canViewFieldLogs = canManageComp

// 当前比赛名（侧栏品牌区）：成员身份自带名称，系统超级管理员按需查询
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
  // 数据管理是按 ?type= 分子模块的，高亮要带上 query 才能对上子菜单项
  if (/\/basedata$/.test(path)) {
    const type = typeof route.query.type === 'string' ? route.query.type : 'materials'
    return `${path}?type=${type}`
  }
  return path
})

/** 停留在数据管理时展开它的子菜单 */
const onDataManagementRoute = computed(() => /\/basedata$/.test(route.path))
const defaultOpeneds = computed(() =>
  onDataManagementRoute.value ? ['data-management'] : [],
)
watch(
  onDataManagementRoute,
  (active) => {
    if (active) nextTick(() => menuRef.value?.open?.('data-management'))
  },
  { immediate: true },
)
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
.brand-meta .meta-fy {
  margin-top: 6px;
}
.brand-meta .meta-name {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.brand-meta .meta-skeleton {
  width: 108px;
  height: 20px;
  margin-bottom: 0;
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
