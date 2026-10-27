/**
 * 动效相关的通用工具（2026-10 全量 UI 优化）。
 *
 * 设计原则：精致克制——只在「数值变化」这类需要引导注意力的地方做动画，
 * 并且一切动画都必须服从系统的「减少动态效果」偏好。
 */

import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

/** 是否处于系统的「减少动态效果」偏好下（每次都实时读取，允许用户中途切换）。 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** 缓动：easeOutExpo（起步快、收尾稳，适合数字落位）。 */
function easeOutExpo(t: number): number {
  return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)
}

export interface CountUpOptions {
  /** 动画时长（毫秒），默认 600ms */
  duration?: number
  /** 小数位，默认 0（金额/分数需要两位时传 2） */
  precision?: number
}

/**
 * 数值滚动：源数值变化时，返回的 ref 从旧值平滑过渡到新值。
 *
 * - 首次赋值不播动画（避免页面一进来所有数字一起跳）；
 * - `prefers-reduced-motion` 下直接返回目标值；
 * - 组件卸载时自动取消 rAF，不会泄漏。
 *
 * @example
 * const score = computed(() => row.score ?? 0)
 * const shown = useCountUp(score, { precision: 2 })
 * // 模板：{{ shown.toFixed(2) }}
 */
export function useCountUp(
  source: Ref<number | null | undefined>,
  options: CountUpOptions = {},
): Ref<number> {
  const duration = options.duration ?? 600
  const precision = options.precision ?? 0
  const round = (n: number): number => {
    const p = Math.pow(10, precision)
    return Math.round(n * p) / p
  }

  const initial = typeof source.value === 'number' ? source.value : 0
  const displayed = ref(initial)
  let frame = 0

  const cancel = (): void => {
    if (frame) {
      cancelAnimationFrame(frame)
      frame = 0
    }
  }

  watch(source, (next) => {
    cancel()
    const to = typeof next === 'number' && Number.isFinite(next) ? next : 0
    const from = displayed.value
    if (from === to || prefersReducedMotion() || duration <= 0) {
      displayed.value = round(to)
      return
    }
    const start = performance.now()
    const step = (now: number): void => {
      const progress = Math.min(1, (now - start) / duration)
      displayed.value = round(from + (to - from) * easeOutExpo(progress))
      if (progress < 1) {
        frame = requestAnimationFrame(step)
      } else {
        frame = 0
        displayed.value = round(to)
      }
    }
    frame = requestAnimationFrame(step)
  })

  onBeforeUnmount(cancel)
  return displayed
}

/**
 * 临时高亮：给刚被实时推送更新的元素加一段时间的高亮类。
 * 页面把它绑到 `:class`，值变化时自动闪一下，让用户知道「这里刚更新了」。
 */
export function useFlash(duration = 1000): {
  flashing: Ref<boolean>
  flash: () => void
} {
  const flashing = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  const flash = (): void => {
    if (prefersReducedMotion()) return
    flashing.value = false
    // 强制下一帧再加类，保证连续两次更新都能重新触发动画
    requestAnimationFrame(() => {
      flashing.value = true
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        flashing.value = false
      }, duration)
    })
  }
  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
  })
  return { flashing, flash }
}
