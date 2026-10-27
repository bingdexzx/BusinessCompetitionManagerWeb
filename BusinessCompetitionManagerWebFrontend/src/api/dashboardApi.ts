// 仪表盘（2026-10 决策：布局来自比赛包 dashboard.json，组件绑定产业字段值，去掉自定义拖拽）
import { http } from './client'

export interface DashboardBind {
  table: 'entity' | 'finance'
  fieldKey: string
  aggregate?: 'sum' | 'latest' | 'average'
  max?: number
}

export interface DashboardComponent {
  id?: string
  type: 'number' | 'gauge' | 'table' | 'text'
  title: string
  zone?: string
  text?: string
  suffix?: string
  description?: string
  bind?: DashboardBind
}

export interface DashboardLayout {
  title: string
  /** 通用区（「全部」页签，聚合全部可操作公司） */
  components: DashboardComponent[]
  /** 按产业分屏：产业key → 该产业专属布局（只聚合该产业公司、绑定该产业字段） */
  industries?: Record<string, { title?: string; components: DashboardComponent[] }>
  updatedAt: string
}

export function getDashboardLayout(cid: number | string): Promise<DashboardLayout> {
  return http.get<DashboardLayout>(`/competitions/${cid}/dashboard`)
}
