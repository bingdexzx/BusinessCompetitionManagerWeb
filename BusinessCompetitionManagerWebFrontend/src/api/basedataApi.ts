// 基础数据 API（数据管理页）。契约：表键 table ∈ fuels/warehouses/vehicles/materials/products/parts/
// infrastructures/tech_nodes/production_lines/map_nodes/map_node_types/path_types；
// GET/POST/PATCH/DELETE /api/competitions/{cid}/basedata/{table}[/{id}]（另加 /{id}/impact）
// 行字段 = 旧项目模型字段 camelCase；POST/PATCH 的 relations 同名数组整体替换；写操作仅超级管理员
import { http } from './client'

export type BasedataTable =
  | 'fuels'
  | 'warehouses'
  | 'vehicles'
  | 'materials'
  | 'products'
  | 'parts'
  | 'infrastructures'
  | 'tech_nodes'
  | 'production_lines'
  | 'map_nodes'
  | 'map_node_types'
  | 'path_types'

export interface BasedataRelations {
  // 关系结构由各基础数据表定义决定（xlsx/插件动态字段），保留动态索引
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any
}

export interface BasedataRow {
  id: number
  name?: string
  createdAt?: string
  updatedAt?: string
  // GET /{id} 与列表行内嵌关联（parts/materials/techRequirements/prerequisites/pathTypes）
  relations?: BasedataRelations | null
  // 行字段随基础数据表变化（动态列），保留动态索引
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any
}

export interface BasedataListParams {
  page?: number
  pageSize?: number
  q?: string
  /** 仅地图节点用：按节点类型名过滤（如「城市点位」） */
  nodeType?: string
}

export interface BasedataListResult {
  items: BasedataRow[]
  total: number
  page: number
  pageSize: number
}

export type BasedataPayload = Record<string, unknown>

export interface BasedataImpactRef {
  kind?: string
  label: string
  count: number
}

export interface BasedataImpact {
  removable?: boolean
  refs?: BasedataImpactRef[]
  name?: string
}

export interface BasedataApi {
  list(cid: string | number, params?: BasedataListParams): Promise<BasedataListResult>
  get(cid: string | number, id: number): Promise<BasedataRow>
  create(cid: string | number, body: BasedataPayload): Promise<BasedataRow>
  update(cid: string | number, id: number, body: BasedataPayload): Promise<BasedataRow>
  remove(cid: string | number, id: number): Promise<{ ok: boolean }>
  impact(cid: string | number, id: number): Promise<BasedataImpact>
}

function root(cid: string | number, table: BasedataTable): string {
  return `/competitions/${cid}/basedata/${table}`
}

export function basedataTableApi(table: BasedataTable): BasedataApi {
  return {
    list(cid, params = {}) {
      return http.get<BasedataListResult>(root(cid, table), {
        query: {
        page: params.page,
        pageSize: params.pageSize,
        q: params.q,
        nodeType: params.nodeType,
      },
      })
    },
    get(cid, id) {
      return http.get<BasedataRow>(`${root(cid, table)}/${id}`)
    },
    create(cid, body) {
      return http.post<BasedataRow>(root(cid, table), body)
    },
    update(cid, id, body) {
      return http.patch<BasedataRow>(`${root(cid, table)}/${id}`, body)
    },
    remove(cid, id) {
      return http.delete<{ ok: boolean }>(`${root(cid, table)}/${id}`)
    },
    impact(cid, id) {
      return http.get<BasedataImpact>(`${root(cid, table)}/${id}/impact`)
    },
  }
}

export const fuelsApi = basedataTableApi('fuels')
export const warehousesApi = basedataTableApi('warehouses')
export const vehiclesApi = basedataTableApi('vehicles')
export const materialsApi = basedataTableApi('materials')
export const productsApi = basedataTableApi('products')
export const partsApi = basedataTableApi('parts')
export const infrastructuresApi = basedataTableApi('infrastructures')
export const techNodesApi = basedataTableApi('tech_nodes')
export const productionLinesApi = basedataTableApi('production_lines')
export const mapNodesApi = basedataTableApi('map_nodes')
export const pathTypesApi = basedataTableApi('path_types')

// 地图节点列表（原料「产地 / 按地点价格」编辑用）；行字段 { id, name, region, x, y, relations: { edgesCount } }
export async function listMapNodes(cid: string | number): Promise<BasedataRow[]> {
  // 地图节点早就超过 500 个（打断后 800+），只取第一页会让「按地点价格」显示成 节点#id，
  // 产地/价格表也就对不上城市名——这里必须翻页取全。
  const pageSize = 500
  const first = await mapNodesApi.list(cid, { page: 1, pageSize })
  const items = [...(first.items ?? [])]
  const total = first.total ?? items.length
  let page = 1
  while (items.length < total) {
    page += 1
    const next = await mapNodesApi.list(cid, { page, pageSize })
    if (!next.items?.length) break
    items.push(...next.items)
  }
  return items
}
