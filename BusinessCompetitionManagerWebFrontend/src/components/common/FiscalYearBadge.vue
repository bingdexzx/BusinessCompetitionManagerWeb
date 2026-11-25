<script setup lang="ts">
// 财年显示器：比赛名称下方展示「当前进行中的财年 + 已进行时长」，每秒刷新；
// 财年开启/结束（广播 resource:changed=fiscal-years）后自动重拉，无需手动刷新。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getFiscalYears } from '@/api'
import type { FiscalYear } from '@/api/types'
import { useResourceRefresh } from '@/composables/useNotifications'

const props = defineProps<{ cid: string | number }>()

const router = useRouter()
const years = ref<FiscalYear[]>([])
const loaded = ref(false)
const now = ref(Date.now())
let ticker: number | undefined

const current = computed<FiscalYear | null>(
  () => years.value.find((y) => y.status === 'OPEN') ?? null,
)

/** 无进行中财年时退回最近一个财年（用于展示「已结束/未开始」状态） */
const target = computed<FiscalYear | null>(() => {
  if (current.value) return current.value
  if (!years.value.length) return null
  return [...years.value].sort((a, b) => b.year - a.year)[0] ?? null
})

const stateLabel = computed(() => {
  if (!loaded.value) return '财年加载中'
  if (!target.value) return '暂无财年'
  return current.value ? '进行中' : target.value.statusLabel || '已结束'
})

/** 已进行时长（天 时:分:秒，每秒更新） */
const elapsed = computed(() => {
  if (!current.value) return ''
  const start = new Date(current.value.openedAt).getTime()
  if (!Number.isFinite(start)) return ''
  const total = Math.max(0, Math.floor((now.value - start) / 1000))
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  const clock = `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`
  return days > 0 ? `${days}天 ${clock}` : clock
})

const ariaLabel = computed(() => {
  if (!target.value) return '当前财年：暂无'
  return current.value
    ? `当前财年 FY${target.value.year} 进行中，已进行 ${elapsed.value}`
    : `当前财年 FY${target.value.year} ${stateLabel.value}`
})

async function load(): Promise<void> {
  if (!props.cid) {
    years.value = []
    loaded.value = true
    return
  }
  try {
    years.value = await getFiscalYears(props.cid)
  } catch {
    years.value = [] // 财年为增强展示，失败不阻塞页面
  } finally {
    loaded.value = true
  }
}

function openFiscalPage(): void {
  void router.push(`/competitions/${props.cid}/fiscal`)
}

watch(() => props.cid, () => void load(), { immediate: true })
// 财年开启/结束、补录审核等写操作后自动重拉（400ms 去抖）
useResourceRefresh(['fiscal-years'], load)

onMounted(() => {
  ticker = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (ticker) window.clearInterval(ticker)
})
</script>

<template>
  <button
    type="button"
    class="fy-badge pressable"
    :class="{
      'is-open': !!current,
      'is-idle': !current,
      'is-empty': loaded && !target,
    }"
    :aria-label="ariaLabel"
    :title="ariaLabel"
    @click="openFiscalPage"
  >
    <span class="fy-dot" aria-hidden="true" />
    <template v-if="!loaded">
      <span class="fy-text">财年加载中…</span>
    </template>
    <template v-else-if="!target">
      <span class="fy-text">暂无财年</span>
    </template>
    <template v-else>
      <span class="fy-year value-num">FY{{ target.year }}</span>
      <span class="fy-state">{{ stateLabel }}</span>
      <span v-if="current && elapsed" class="fy-elapsed value-num">{{ elapsed }}</span>
    </template>
  </button>
</template>

<style scoped>
.fy-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 2px 9px;
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--surface-sunken);
  color: var(--color-text-secondary);
  font-size: var(--font-xs);
  line-height: 20px;
  cursor: pointer;
  transition:
    border-color var(--dur-fast) var(--ease-standard),
    background-color var(--dur-fast) var(--ease-standard);
}

.fy-badge:hover {
  border-color: var(--color-primary);
  background: var(--color-surface);
}

.fy-badge:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.fy-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
  background: var(--color-text-tertiary);
}

.fy-badge.is-open .fy-dot {
  background: var(--color-success);
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.16);
}

.fy-year {
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: 0.02em;
}

.fy-badge.is-open .fy-year {
  color: var(--color-primary);
}

.fy-state {
  color: var(--color-text-secondary);
}

.fy-elapsed {
  color: var(--color-text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fy-text {
  color: var(--color-text-tertiary);
  white-space: nowrap;
}

.fy-badge.is-empty .fy-dot {
  background: var(--color-border);
  box-shadow: none;
}

/* 侧栏等窄容器：状态与计时允许省略，避免撑破 */
@media (max-width: 1024px) {
  .fy-elapsed {
    max-width: 96px;
  }
}
</style>
