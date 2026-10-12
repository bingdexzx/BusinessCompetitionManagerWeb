// 基础数据 API（数据管理页）—— 新后端统一契约封装。
//
// 契约（表键 table ∈ fuels/warehouses/vehicles/materials/products/parts/
//      infrastructures/tech_nodes/production_lines/map_nodes/map_node_types/path_types）：
//   GET    /api/competitions/{cid}/basedata/{table}?page&pageSize&q → { items, total, page, pageSize }
//   POST   /api/competitions/{cid}/basedata/{table}                 → 行
//   GET    /api/competitions/{cid}/basedata/{table}/{id}            → 行（含 relations）
//   PATCH  /api/competitions/{cid}/basedata/{table}/{id}            → 行
//   DELETE /api/competitions/{cid}/basedata/{table}/{id}            → { ok: true }
//   GET    /api/competitions/{cid}/basedata/{table}/{id}/impact     → { removable, refs: [{ kind, label, count }] }
//
// 行字段 = 旧项目模型字段 camelCase（pricePerLiter、capacity、price、type、
// fuelConsumptionPerKm、maxMaterialCargo/maxPartCargo/maxProductCargo、carbonEmission、
// origin、carbonEmissionCoefficient、nodePrices、footprint、employmentRateBonus、
// populationBonus、highQualityPopulationBonus、happinessIndexBonus、perCapitaIncomeBonus、
// carbonReductionBonus、activationPrice、description、tier、researchCost、laborCount、maxPerYear …）。
//
// relations 内嵌（GET 行上读取；POST/PATCH body 里以同名数组整体替换，嵌套在 relations 下）：
//   products    → relations.parts / relations.techRequirements
//   parts       → relations.materials / relations.techRequirements
//   tech_nodes  → relations.prerequisites
//   vehicles    → relations.pathTypes（[{ id, pathTypeId, pathTypeName }]）
//
// 写操作（create/update/remove）仅超管可用（isSuperuser || 本比赛 COMP_SUPER_ADMIN）。
import { http } from './client'

/** 基础数据表键 */
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

/** 行内嵌关联（products/parts/tech_nodes/vehicles 等） */
export interface BasedataRelations {
  [key: string]: any
}

/** 基础数据行：id + 各表字段（camelCase），其余列以索引签名兜底 */
export interface BasedataRow {
  id: number
  name?: string
  createdAt?: string
  updatedAt?: string
  /** GET /{id} 与列表行内嵌关联（parts/materials/techRequirements/prerequisites/pathTypes） */
  relations?: BasedataRelations | null
  [key: string]: any
}

/** 列表入参（?page&pageSize&q） */
export interface BasedataListParams {
  page?: number
  pageSize?: number
  q?: string
}

/** 列表回包 */
export interface BasedataListResult {
  items: BasedataRow[]
  total: number
  page: number
  pageSize: number
}

/** POST/PATCH 请求体：行字段 + relations 同名数组整体替换 */
export type BasedataPayload = Record<string, any>

/** 删除影响条目（GET .../{id}/impact → refs[]） */
export interface BasedataImpactRef {
  kind?: string
  label: string
  count: number
}

/** 删除影响（GET .../{id}/impact） */
export interface BasedataImpact {
  removable?: boolean
  refs?: BasedataImpactRef[]
  name?: string
}

/** 单表 CRUD（同名函数：list/get/create/update/remove/impact） */
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

/** 按表键生成统一 CRUD 封装 */
export function basedataTableApi(table: BasedataTable): BasedataApi {
  return {
    list(cid, params = {}) {
      return http.get<BasedataListResult>(root(cid, table), {
        query: { page: params.page, pageSize: params.pageSize, q: params.q },
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

// ---------- 各管理器使用的表 API（函数名与旧项目 xxApi 保持一致） ----------
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
export const mapNodeTypesApi = basedataTableApi('map_node_types')
export const pathTypesApi = basedataTableApi('path_types')

/**
 * 地图节点列表（原料「产地 / 按地点价格」编辑用）。
 * 走同一 /basedata 契约；行字段 { id, name, region, x, y, relations: { edgesCount } }。
 */
export function listMapNodes(cid: string | number): Promise<BasedataRow[]> {
  return mapNodesApi.list(cid, { page: 1, pageSize: 500 }).then((res) => res.items ?? [])
}
