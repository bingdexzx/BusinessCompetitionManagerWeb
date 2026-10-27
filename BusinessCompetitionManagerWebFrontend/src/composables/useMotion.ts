// 动效工具：只在「数值变化」这类需要引导注意力的地方做动画，且一律服从系统「减少动态效果」偏好

import { onBeforeUnmount, ref, watch, type Ref } from 'vue'

/** 是否处于系统「减少动态效果」偏好（每次实时读取，允许用户中途切换） */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function easeOutExpo(t: number): number {
  return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t)
}

export interface CountUpOptions {
  duration?: number
  precision?: number
}

/** 数值滚动：源值变化时平滑过渡；首次赋值不播动画，prefers-reduced-motion 下直接返回目标值，卸载自动取消 rAF */
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
  // 首屏拿到的第一个真实值直接落定：否则会从 0 滚到目标值，看起来像"先显示 0 再变对"
  let seeded = typeof source.value === 'number'
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
    if (!seeded) {
      seeded = true
      displayed.value = round(to)
      return
    }
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

/** 临时高亮：给刚被实时推送更新的元素闪一下高亮类 */
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
