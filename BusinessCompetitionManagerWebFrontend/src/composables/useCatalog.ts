// 产业/字段「键 → 中文名」目录（比赛级，进程内缓存 + 实时变更自动失效）
//
// 比赛包里的产业键（manufacturer）、字段键（cash）只是标识，界面必须显示中文名
// （插件 INDUSTRY_NAME / FIELDS[].name）。多个页面同时用这份目录，故按比赛缓存，
// 避免每个页面各拉一次；比赛包导入会改产业与字段 → 订阅 packages/basedata 自动失效。
import { computed, ref, watch, type Ref } from 'vue'
import { getContractTypes, getIndustries, getIndustryFields } from '@/api'
import type { ContractType, IndustryFieldMeta, IndustryOption } from '@/api/types'
import { useResourceRefresh } from '@/composables/useNotifications'

interface CatalogEntry {
  industries: Ref<IndustryOption[]>
  fields: Ref<IndustryFieldMeta[]>
  contractTypes: Ref<ContractType[]>
  loading: Ref<boolean>
  ready: Ref<boolean>
  load: () => Promise<void>
}

/** cid → 目录（同一比赛的所有页面共用一份，拿到的是同一组 ref） */
const cache = new Map<string, CatalogEntry>()

function createEntry(cid: Ref<string>): CatalogEntry {
  const industries = ref<IndustryOption[]>([])
  const fields = ref<IndustryFieldMeta[]>([])
  const contractTypes = ref<ContractType[]>([])
  const loading = ref(false)
  const ready = ref(false)
  let pending: Promise<void> | null = null

  async function load(): Promise<void> {
    if (!cid.value) return
    if (pending) return pending
    loading.value = true
    pending = (async () => {
      try {
        const [industryRows, fieldRows, typeRows] = await Promise.all([
          getIndustries(cid.value).catch(() => [] as IndustryOption[]),
          getIndustryFields(cid.value).catch(() => [] as IndustryFieldMeta[]),
          getContractTypes(cid.value).catch(() => [] as ContractType[]),
        ])
        industries.value = industryRows
        fields.value = fieldRows
        contractTypes.value = typeRows
        ready.value = true
      } finally {
        loading.value = false
        pending = null
      }
    })()
    return pending
  }

  void load()
  return { industries, fields, contractTypes, loading, ready, load }
}

/**
 * 取某比赛的展示目录。
 *
 * @example
 * const catalog = useCatalog(() => props.cid)
 * catalog.industryLabel(team.industryFinal)  // '制造业'（找不到时回退原 key）
 * catalog.fieldLabel('cash')                 // '现金'
 */
export function useCatalog(cidSource: () => string) {
  const cid = computed(() => String(cidSource() || ''))

  const entry = (): CatalogEntry => {
    const key = cid.value
    let hit = cache.get(key)
    if (!hit) {
      const created = createEntry(cid)
      cache.set(key, created)
      hit = created
    }
    return hit
  }

  const current = entry()

  // 换比赛 → 换目录（旧缓存保留，来回切不用重拉）
  watch(
    cid,
    () => {
      void entry().load()
    },
    { immediate: false },
  )

  // 比赛包导入/基础数据变更可能新增产业或字段
  useResourceRefresh(['packages', 'basedata'], () => {
    void entry().load()
  })

  const industryNameMap = computed(
    () => new Map(current.industries.value.map((row) => [row.key, row.name || row.key])),
  )
  const fieldNameMap = computed(
    () => new Map(current.fields.value.map((row) => [row.key, row.name || row.key])),
  )

  /** 产业键 → 中文名；未知键回退为键本身，绝不显示空白 */
  function industryLabel(key: string | null | undefined): string {
    const raw = String(key ?? '')
    if (!raw) return ''
    return industryNameMap.value.get(raw) ?? raw
  }

  /** 字段键 → 中文名；未知键回退为键本身 */
  function fieldLabel(key: string | null | undefined): string {
    const raw = String(key ?? '')
    if (!raw) return ''
    return fieldNameMap.value.get(raw) ?? raw
  }

  /** 合同类型键 → 中文名（CONTRACT_NAME）；未知回退为键 */
  function contractTypeLabel(key: string | null | undefined): string {
    const raw = String(key ?? '')
    if (!raw) return ''
    return current.contractTypes.value.find((row) => row.key === raw)?.name || raw
  }

  function typeOf(key: string | null | undefined) {
    const raw = String(key ?? '')
    return current.contractTypes.value.find((row) => row.key === raw) ?? null
  }

  /** 合同输入项键 → 中文名（插件 INPUT_SCHEMA[].label）；未知回退为键 */
  function inputLabel(typeKey: string | null | undefined, inputKey: string | null | undefined): string {
    const raw = String(inputKey ?? '')
    if (!raw) return ''
    const row = typeOf(typeKey)?.inputSchema?.find((item) => item.key === raw)
    return row?.label || raw
  }

  /** 参与方角色 → 中文名（插件 PARTY_ROLES[].label）；未知回退为角色键 */
  function partyRoleLabel(
    typeKey: string | null | undefined,
    role: string | null | undefined,
  ): string {
    const raw = String(role ?? '')
    if (!raw) return ''
    const row = typeOf(typeKey)?.partyRoles?.find((item) => item.role === raw)
    return row?.label || raw
  }

  /** 下拉选项：value=key，label=中文名（名字里带 key 便于排错时对照） */
  const industryOptions = computed(() =>
    current.industries.value.map((row) => ({
      value: row.key,
      label: row.name && row.name !== row.key ? `${row.name}（${row.key}）` : row.key,
      name: row.name || row.key,
    })),
  )
  const fieldOptions = computed(() =>
    current.fields.value.map((row) => ({
      value: row.key,
      label: row.name && row.name !== row.key ? `${row.name}（${row.key}）` : row.key,
      name: row.name || row.key,
      fieldType: row.fieldType,
    })),
  )

  return {
    industries: current.industries,
    fields: current.fields,
    contractTypes: current.contractTypes,
    loading: current.loading,
    ready: current.ready,
    industryLabel,
    fieldLabel,
    contractTypeLabel,
    inputLabel,
    partyRoleLabel,
    industryOptions,
    fieldOptions,
    reload: () => entry().load(),
  }
}
