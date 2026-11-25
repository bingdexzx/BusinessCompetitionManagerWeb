// 地图管理基础数据 API：封装 /competitions/{cid}/basedata/{table} 下 4 张地图表的通用调用
//   map_node_types（节点类型）/ path_types（路径类型）/ map_nodes（地图节点）/ map_edges（地图边）
// 契约：
//   GET    /api/competitions/{cid}/basedata/{table}            → {items,total,page,pageSize}
//   POST   /api/competitions/{cid}/basedata/{table}            → 行
//   GET    /api/competitions/{cid}/basedata/{table}/{id}       → 行（含 relations）
//   PATCH  /api/competitions/{cid}/basedata/{table}/{id}       → 行
//   DELETE /api/competitions/{cid}/basedata/{table}/{id}       → {ok:true}
//   GET    /api/competitions/{cid}/basedata/{table}/{id}/impact → {removable, refs:[{kind,label,count}]}
// 写操作仅系统超级管理员（比赛超级管理员身份已取消，2026-11）。
import { http } from './client'
import type {
  MapEdgePayload,
  MapEdgeRow,
  MapImpact,
  MapNodePayload,
  MapNodeRow,
  MapNodeTypePayload,
  MapNodeTypeRow,
  MapPage,
  PathTypePayload,
  PathTypeRow,
} from './mapTypes'

/** 地图相关的 4 张 basedata 表 */
export type MapBasedataTable = 'map_node_types' | 'path_types' | 'map_nodes' | 'map_edges'

export interface MapListParams {
  /** 过滤关键字（code/name） */
  q?: string
  page?: number
  pageSize?: number
}

/** 单表 CRUD 封装：cid 为路由 prop（比赛 id） */
export interface MapTableApi<TRow, TPayload> {
  list(cid: number | string, params?: MapListParams): Promise<MapPage<TRow>>
  get(cid: number | string, id: number): Promise<TRow>
  create(cid: number | string, payload: TPayload): Promise<TRow>
  update(cid: number | string, id: number, payload: TPayload): Promise<TRow>
  remove(cid: number | string, id: number): Promise<{ ok: boolean }>
  impact(cid: number | string, id: number): Promise<MapImpact>
}

function tableApi<TRow, TPayload>(table: MapBasedataTable): MapTableApi<TRow, TPayload> {
  const base = (cid: number | string) => `/competitions/${cid}/basedata/${table}`
  return {
    list(cid, params = {}) {
      return http.get<MapPage<TRow>>(base(cid), {
        query: { q: params.q, page: params.page, pageSize: params.pageSize },
      })
    },
    get(cid, id) {
      return http.get<TRow>(`${base(cid)}/${id}`)
    },
    create(cid, payload) {
      return http.post<TRow>(base(cid), payload)
    },
    update(cid, id, payload) {
      return http.patch<TRow>(`${base(cid)}/${id}`, payload)
    },
    remove(cid, id) {
      return http.delete<{ ok: boolean }>(`${base(cid)}/${id}`)
    },
    impact(cid, id) {
      return http.get<MapImpact>(`${base(cid)}/${id}/impact`)
    },
  }
}

/** 节点类型（MapNodeType：name/description/color） */
export const mapNodeTypeApi = tableApi<MapNodeTypeRow, MapNodeTypePayload>('map_node_types')

/** 路径类型（PathType：name/description/color） */
export const pathTypeApi = tableApi<PathTypeRow, PathTypePayload>('path_types')

/** 地图节点（MapNode：name/region/nodeTypeId/x/y，relations.edgesCount） */
export const mapNodeApi = tableApi<MapNodeRow, MapNodePayload>('map_nodes')

/** 地图边（MapEdge：distance + nodeAId/nodeBId/pathTypeId） */
export const mapEdgeApi = tableApi<MapEdgeRow, MapEdgePayload>('map_edges')

// ---------- QGIS 地图（.qgz 工程导入 + 经纬度坐标模式） ----------

/** 地图坐标模式：PIXEL=画布像素（手绘），GEO=经纬度（QGIS 导入） */
export type MapMode = 'PIXEL' | 'GEO'

/** 地图配置（GET .../basedata/map-settings） */
export interface MapSettings {
  mode: MapMode
  /** 经纬度范围 [minLon, minLat, maxLon, maxLat]，GEO 模式下用于投影 */
  bounds: number[]
  /** 区域面（GeoJSON 环）：[{name, rings: [[[lon,lat], ...], ...]}] */
  regions: Array<{ name: string; rings: number[][][] }>
  /** 多图层地图（.qgz 导入）：点/线图层 + 面图层 */
  layers?: import('./mapTypes').MapLayerSetting[]
  source: string
  importedAt: string | null
}

/** QGIS 工程导入报告（POST .../basedata/map-import） */
export interface MapImportReport {
  nodesCreated: number
  nodesReused: number
  edgesCreated: number
  edgesSkipped: number
  nodeTypesCreated: number
  pathTypesCreated: number
  layers?: number
  regionPolygons?: number
  missingLayers?: string[]
  regions: number
  bounds: number[]
}

export function getMapSettings(cid: number | string): Promise<MapSettings> {
  return http.get<MapSettings>(`/competitions/${cid}/basedata/map-settings`)
}

/** 导入 QGIS 工程文件 .qgz（点→节点、线→边、面→区域） */
export function importQGISMap(
  cid: number | string,
  file: File,
  options: { replace?: boolean } = {},
): Promise<MapImportReport> {
  const form = new FormData()
  form.append('file', file)
  if (options.replace) form.append('replace', 'true')
  return http.post<MapImportReport>(`/competitions/${cid}/basedata/map-import`, form)
}
