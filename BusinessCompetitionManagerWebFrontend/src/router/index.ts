import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/competitions' },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/RegisterView.vue'),
      meta: { public: true },
    },
    {
      path: '/competitions',
      name: 'competitions',
      component: () => import('../views/CompetitionsView.vue'),
    },
    {
      path: '/competitions/:cid',
      name: 'competition-detail',
      component: () => import('../views/CompetitionDetailView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/teams',
      name: 'competition-teams',
      component: () => import('../views/TeamsView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/contracts',
      name: 'competition-contracts',
      component: () => import('../views/ContractsView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/stocks',
      name: 'competition-stocks',
      component: () => import('../views/StockMarketView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/stocks/manage',
      name: 'competition-stocks-manage',
      component: () => import('../views/StockManageView.vue'),
      props: true,
      meta: { participant: true }, // 交易管理需参赛身份
    },
    {
      path: '/competitions/:cid/contracts/:id',
      name: 'contract-detail',
      component: () => import('../views/ContractDetailView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/fiscal',
      name: 'competition-fiscal',
      component: () => import('../views/FiscalView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/basedata',
      name: 'competition-basedata',
      component: () => import('../views/BasedataView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/settlement',
      name: 'competition-settlement',
      component: () => import('../views/SettlementView.vue'),
      props: true,
      meta: { manager: true },
    },
    {
      path: '/competitions/:cid/logs',
      name: 'competition-logs',
      component: () => import('../views/FieldLogsView.vue'),
      props: true,
    },
    {
      path: '/competitions/:cid/audit',
      name: 'competition-audit',
      component: () => import('../views/AuditLogView.vue'),
      props: true,
      meta: { manager: true },
    },
    {
      path: '/messages',
      name: 'messages',
      component: () => import('../views/MessagesView.vue'),
    },
    {
      path: '/profile',
      name: 'profile',
      component: () => import('../views/ProfileView.vue'),
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('../views/LogsView.vue'),
      meta: { superuser: true },
    },
    {
      path: '/plugins',
      name: 'plugins',
      component: () => import('../views/PluginsView.vue'),
      meta: { superuser: true },
    },
    { path: '/:pathMatch(.*)*', redirect: '/competitions' },
  ],
})

// 路由守卫：未登录跳 /login；系统页仅系统超管；已登录不进登录/注册页
router.beforeEach((to) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (auth.isAuthenticated) return { name: 'competitions' }
    return true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.meta.superuser && !auth.isSuperuser) {
    return { name: 'competitions' }
  }

  // cid 必须是纯数字：拦截 /competitions/undefined 等非法链接
  //（否则页面会以 undefined 发 /api/competitions/undefined/... 请求 → 404 噪音）
  const rawCid = to.params.cid
  if (rawCid !== undefined && !/^\d+$/.test(String(rawCid))) {
    return { name: 'competitions' }
  }

  // 超管页（结算 / 审计日志）：系统超管 或 本比赛超管（与后端权限一致）
  if (to.meta.manager) {
    const cid = String(to.params.cid ?? '')
    const isCompSuperAdmin = auth.memberships.some(
      (m) => String(m.id) === cid && m.identity === 'COMP_SUPER_ADMIN',
    )
    if (!auth.isSuperuser && !isCompSuperAdmin) {
      return { name: 'competitions' }
    }
  }

  // 参赛页（股票交易管理）：本比赛成员（参赛身份）或 系统超管
  if (to.meta.participant) {
    const cid = String(to.params.cid ?? '')
    const isMember = auth.memberships.some((m) => String(m.id) === cid)
    if (!auth.isSuperuser && !isMember) {
      return { name: 'competitions' }
    }
  }

  return true
})

export default router
