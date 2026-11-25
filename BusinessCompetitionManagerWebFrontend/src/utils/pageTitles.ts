/**
 * 顶栏面包屑的页面名（2026-11 统一）：与侧栏、页面 h1 用同一套叫法。
 * 任何页面都应返回非空标题；新增路由时在这里登记，避免某些页面只剩「商赛辅助办赛系统」。
 */

const STANDALONE: Record<string, string> = {
  '/competitions': '比赛列表',
  '/messages': '消息中心',
  '/profile': '个人档案',
  '/logs': '网络日志中心',
  '/plugins': '插件管理',
  '/users': '账号管理',
  '/schools': '学校管理',
  '/settings': '系统设置',
  '/update-logs': '更新日志',
}

const SECTIONS: Record<string, string> = {
  teams: '组队管理',
  companies: '公司管理',
  contracts: '合同工作台',
  fiscal: '财年管理',
  settlement: '结算管理',
  logs: '字段日志',
  audit: '审计流水',
  'region-overview': '区域总览',
  plugins: '插件管理',
  dashboard: '仪表盘',
  maps: '地图管理',
}

const BASEDATA_TYPES: Record<string, string> = {
  materials: '原料管理',
  parts: '零件管理',
  products: '产品管理',
  fuels: '燃料管理',
  warehouses: '仓库管理',
  vehicles: '载具管理',
  infrastructures: '基建管理',
  'production-lines': '生产线管理',
  'tech-tree': '科技树管理',
  maps: '地图管理',
}

const TOOLS: Record<string, string> = {
  'material-price': '原料价格工具',
  'part-materials': '零件用量',
  'product-parts': '产品用量',
  navigation: '路径导航',
  timers: '计时器',
}

/** 路由 → 页码名（永不为空） */
export function pageTitleOf(path: string, query: Record<string, unknown> = {}): string {
  const clean = path.replace(/\/+$/, '') || '/'
  if (STANDALONE[clean]) return STANDALONE[clean]

  const toolMatch = /^\/competitions\/[^/]+\/tools\/([^/]+)/.exec(clean)
  if (toolMatch) return TOOLS[toolMatch[1] ?? ''] ?? '工具箱'

  const competitionMatch = /^\/competitions\/([^/]+)(?:\/([^/]+))?(?:\/([^/]+))?/.exec(clean)
  if (!competitionMatch) return ''

  const section = competitionMatch[2] ?? ''
  const sub = competitionMatch[3] ?? ''
  if (!section) return '比赛详情'
  if (section === 'contracts') return sub ? '合同详情' : '合同工作台'
  if (section === 'stocks') {
    if (sub === 'manage') return '交易管理'
    if (sub === 'admin') return '股票管理'
    return '股票行情'
  }
  if (section === 'basedata') {
    const type = String(query.type ?? 'materials')
    return BASEDATA_TYPES[type] ?? '数据管理'
  }
  return SECTIONS[section] ?? ''
}
