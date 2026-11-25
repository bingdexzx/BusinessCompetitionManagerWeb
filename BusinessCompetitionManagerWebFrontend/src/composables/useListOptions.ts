import { ref } from 'vue'

import { getCompanies } from '@/api'
import {
  fuelsApi,
  infrastructuresApi,
  listMapNodes,
  materialsApi,
  mapNodesApi,
  partsApi,
  productionLinesApi,
  productsApi,
  techNodesApi,
  vehiclesApi,
  warehousesApi,
} from '@/api/basedataApi'
import { http } from '@/api/client'

/**
 * 合同 LIST 输入的行选项（按 `LIST:<table>` 里的引用表取基础数据）。
 *
 * 支持 materials / parts / products / map_nodes 四张表（引擎 `_ref_exists` 同口径），
 * 同一张表在一个页面里只拉一次。
 */
export interface ListOption {
  id: number
  /** 存进合同的值（基础数据的名称） */
  name: string
  /** 下拉里显示的文字（缺省用 name；地图节点会补上所属区域） */
  label?: string
}

/** 地图里自动命名的路网点（``节点(x,y)``）不是可采购地点，不进选项。 */
const ANONYMOUS_NODE = /^\s*节点\(/

const LOADERS: Record<string, (cid: number) => Promise<ListOption[]>> = {
  materials: async (cid) => {
    const page = await materialsApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  parts: async (cid) => {
    const page = await partsApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  products: async (cid) => {
    const page = await productsApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  fuels: async (cid) => {
    const page = await fuelsApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  tech_nodes: async (cid) => {
    const page = await techNodesApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  infrastructures: async (cid) => {
    const page = await infrastructuresApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  warehouses: async (cid) => {
    const page = await warehousesApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  production_lines: async (cid) => {
    const page = await productionLinesApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  vehicles: async (cid) => {
    const page = await vehiclesApi.list(cid, { page: 1, pageSize: 500 })
    return (page.items ?? []) as ListOption[]
  },
  cities: async (cid) => {
    // 只取「城市点位」节点：矿点/车站/路网顶点不进合同下拉
    const page = await mapNodesApi.list(cid, { page: 1, pageSize: 500, nodeType: '城市点位' })
    return (page.items ?? []) as ListOption[]
  },
  companies: async (cid) => {
    // 兼容数组与 {items} 两种返回形状
    type CompanyRow = { id: number; name: string }
    const res = await getCompanies(cid)
    const rows = Array.isArray(res) ? (res as CompanyRow[]) : []
    return rows.map((company) => ({ id: company.id, name: company.name }))
  },
  regions: async (cid) => {
    // 该接口直接返回数组（不是 {items}）；兼容两种形状，避免下拉为空
    type RegionRow = { id: number; name: string }
    const res = await http.get<RegionRow[] | { items: RegionRow[] }>(
      `/competitions/${cid}/regions`,
    )
    const rows = Array.isArray(res) ? res : (res.items ?? [])
    return rows.map((region) => ({ id: region.id, name: region.name }))
  },
  map_nodes: async (cid) => {
    const rows = (await listMapNodes(cid)) as Array<ListOption & { region?: string }>
    // 去掉自动命名的路网点（节点(x,y)），同名节点只留第一条（下拉里重复会让人选错）
    const seen = new Set<string>()
    const options: ListOption[] = []
    for (const row of rows) {
      const name = String(row.name ?? '').trim()
      if (!name || ANONYMOUS_NODE.test(name) || seen.has(name)) continue
      seen.add(name)
      options.push({
        id: row.id,
        name,
        label: row.region ? `${name} · ${row.region}` : name,
      })
    }
    return options
  },
}

/** `LIST:parts` → `parts`；不是清单类型返回空串。 */
export function listTableOf(type: string | undefined): string {
  const raw = String(type ?? '')
  if (!raw.toUpperCase().startsWith('LIST')) return ''
  return raw.split(':')[1]?.trim().toLowerCase() || 'materials'
}

/** `REF:companies` → `companies`；不是 REF 类型返回空串。 */
export function refTableOf(type: string | undefined): string {
  const raw = String(type ?? '')
  if (!raw.toUpperCase().startsWith('REF')) return ''
  return (raw.split(':')[1] ?? '').trim().toLowerCase()
}

export function useListOptions(cid: number) {
  const options = ref<Record<string, ListOption[]>>({})
  const loading = ref<Record<string, boolean>>({})

  /** 按引用表懒加载选项（失败按空列表处理，不影响表单其余部分）。 */
  async function ensure(table: string): Promise<ListOption[]> {
    if (!table) return []
    const existing = options.value[table]
    if (existing) return existing
    if (loading.value[table]) return []
    const loader = LOADERS[table]
    if (!loader) return []
    loading.value[table] = true
    try {
      const items = await loader(cid)
      options.value = { ...options.value, [table]: items }
      return items
    } catch {
      options.value = { ...options.value, [table]: [] }
      return []
    } finally {
      loading.value = { ...loading.value, [table]: false }
    }
  }

  /** 模板里直接用：`optionsFor(f.type)`（LIST: 与 REF: 都按同一张表取选项）。 */
  function optionsFor(type: string | undefined): ListOption[] {
    const table = listTableOf(type) || refTableOf(type)
    if (table && !options.value[table]) void ensure(table)
    return options.value[table] ?? []
  }

  return { optionsFor, ensure, listTableOf, refTableOf }
}
