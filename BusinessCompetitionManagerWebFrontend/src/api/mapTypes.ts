// 地图管理（数据管理 · 地图管理）基础数据类型。
// 对应新后端 /competitions/{cid}/basedata/{table} 通用契约，table ∈
// map_node_types（MapNodeType）/ path_types（PathType）/ map_nodes（MapNode）/ map_edges（MapEdge），
// 字段名为旧项目 apps/maps/models.py 的 camelCase。
import type { BasedataPage } from './types'

/** 删除影响查询（GET .../{id}/impact）：是否可直接删除 + 被引用清单 */
export interface MapImpactRef {
  /** 引用方类别（如 map_nodes / map_edges） */
  kind: string
  /** 展示用中文标签 */
  label: string
  /** 引用条数 */
  count: number
}

export interface MapImpact {
  /** false 表示存在阻断性引用，后端将拒绝删除 */
  removable: boolean
  refs: MapImpactRef[]
}

/** 通用分页（与 BasedataPage 同构，泛型化便于各表复用） */
export type MapPage<T> = Omit<BasedataPage, 'items'> & { items: T[] }

/** 节点类型（MapNodeType）行 */
export interface MapNodeTypeRow {
  id: number
  name: string
  description?: string | null
  color?: string | null
  createdAt?: string
  updatedAt?: string
  [key: string]: unknown
}

/** 路径类型（PathType）行 */
export interface PathTypeRow {
  id: number
  name: string
  description?: string | null
  color?: string | null
  createdAt?: string
  updatedAt?: string
  [key: string]: unknown
}

/** 地图节点（MapNode）行的 relations（GET 单行返回「行 + relations」） */
export interface MapNodeRelations {
  /** 关联地图边数量 */
  edgesCount?: number
  /** 所属节点类型（冗余展开，便于列表直接渲染） */
  nodeType?: Pick<MapNodeTypeRow, 'id' | 'name' | 'color'> | null
  [key: string]: unknown
}

/** 地图节点（MapNode）行 */
export interface MapNodeRow {
  id: number
  name: string
  region?: string | null
  /** 所属节点类型（MapNode.node_type 的 camelCase） */
  nodeTypeId?: number | null
  x: number
  y: number
  relations?: MapNodeRelations
  createdAt?: string
  updatedAt?: string
  [key: string]: unknown
}

/** 地图边（MapEdge）行的 relations */
export interface MapEdgeRelations {
  nodeA?: Pick<MapNodeRow, 'id' | 'name'> | null
  nodeB?: Pick<MapNodeRow, 'id' | 'name'> | null
  pathType?: Pick<PathTypeRow, 'id' | 'name' | 'color'> | null
  [key: string]: unknown
}

/** 地图边（MapEdge）行：distance + nodeAId/nodeBId/pathTypeId */
export interface MapEdgeRow {
  id: number
  distance?: number | null
  nodeAId: number
  nodeBId: number
  pathTypeId?: number | null
  relations?: MapEdgeRelations
  createdAt?: string
  updatedAt?: string
  [key: string]: unknown
}

// ---------- 写入载荷（POST / PATCH body） ----------

export interface MapNodeTypePayload {
  name?: string
  description?: string | null
  color?: string | null
}

export type PathTypePayload = MapNodeTypePayload

export interface MapNodePayload {
  name?: string
  region?: string | null
  nodeTypeId?: number | null
  x?: number
  y?: number
}

export interface MapEdgePayload {
  distance?: number | null
  nodeAId?: number
  nodeBId?: number
  pathTypeId?: number | null
}
