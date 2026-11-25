<template>
  <Teleport to="body" :disabled="inline || bare">
    <div
      ref="rootRef"
      class="jt-overlay"
      :class="{ 'is-inline': inline, 'is-bare': bare }"
      role="dialog"
      :aria-modal="inline ? undefined : 'true'"
      aria-labelledby="jt-title"
      tabindex="-1"
      @keydown="onKeydown"
    >
      <div v-if="!inline && !bare" class="jt-bg" aria-hidden="true">
        <div class="jt-bg-glow"></div>
        <div class="jt-bg-grid"></div>
      </div>

      <img
        v-if="imageOnly && ticketImageSrc"
        class="jt-image-only"
        :src="ticketImageSrc"
        :alt="competitionName"
      />
      <div v-else class="jt-stage">
        <header v-if="!inline && !bare" class="jt-heading">
          <span class="jt-badge"><span class="jt-badge-dot"></span>已成功加入</span>
          <h2 class="jt-heading-title">你的参赛凭证</h2>
        </header>

        <div class="jt-machine" :class="`is-${phase}`">
          <div class="jt-shadow" aria-hidden="true"></div>

          <div class="jt-ticket-wrap">
            <!-- 出票机头：票据从这条缝里被推出来 -->
            <div class="jt-printer" :class="`is-${phase}`" aria-hidden="true">
              <span class="jt-printer-led"></span>
              <span class="jt-printer-label">TICKET</span>
              <span class="jt-printer-slot"></span>
            </div>

            <!-- 出票窗口：上沿就是出票口，票据在窗口内向下滑出 -->
            <div class="jt-window" :class="{ 'is-flying': phase === 'flying' }">
              <div
                ref="ticketRef"
                class="jt-ticket"
                :class="{
                  'is-flying': phase === 'flying',
                  'is-torn': torn,
                  'has-image': Boolean(ticketImageSrc),
                  'has-stub': !bare || stub,
                }"
              >
              <div class="jt-gloss" aria-hidden="true"></div>

              <section
                class="jt-main"
                :class="{ 'has-image': Boolean(ticketImageSrc) }"
                :style="mainStyle"
              >
                <header class="jt-head">
                  <span class="jt-brand">纪念券</span>
                </header>

                <footer class="jt-main-foot">
                  <span id="jt-title" class="jt-main-name" :title="competitionName">{{
                    competitionName
                  }}</span>
                  <span class="jt-main-time jt-mono">{{ timeText }}</span>
                  <span class="jt-main-no jt-mono">{{ ticketNo }}</span>
                </footer>

              </section>

              <aside v-if="!bare || stub" class="jt-stub" aria-label="票根">
                <span class="jt-stub-label">副券</span>

                <dl class="jt-info">
                  <div>
                    <dt>持有人</dt>
                    <dd>{{ userName || '参赛代表' }}</dd>
                  </div>
                  <div>
                    <dt>身份</dt>
                    <dd>{{ identityLabel || '参赛代表' }}</dd>
                  </div>
                  <div>
                    <dt>票据编号</dt>
                    <dd class="jt-mono">{{ ticketNo }}</dd>
                  </div>
                </dl>

                <span class="jt-barcode" aria-hidden="true">
                  <i
                    v-for="(width, index) in barcodeBars"
                    :key="index"
                    :style="{ width: `${width}px` }"
                  ></i>
                </span>
                <span class="jt-stub-no">{{ ticketNo }}</span>
              </aside>

              <!-- 沿虚线向下划一下 = 把票根撕下来 -->
              <span
                v-if="showTearHandle && !torn"
                class="jt-tear-handle"
                :class="{ 'is-active': tearing }"
                aria-hidden="true"
                @pointerdown="onTearStart"
                @pointermove="onTearMove"
                @pointerup="onTearEnd"
                @pointercancel="onTearEnd"
              ></span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="!inline && !bare && phase === 'flying'" class="jt-status" aria-live="polite">
          出票中…
        </div>

        <div v-else-if="!inline && !bare" class="jt-actions">
          <button type="button" class="jt-btn jt-btn--ghost" @click="downloadTicket">
            保存票据
          </button>
          <button ref="enterRef" type="button" class="jt-btn jt-btn--primary" @click="onEnter">
            进入比赛 →
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { toPng } from 'html-to-image'
import { useAuthedImage } from '@/composables/useAuthedImage'

const props = withDefaults(
  defineProps<{
    competitionId: number
    competitionName: string
    identityLabel?: string
    userName?: string
    joinedAt?: string
    ticketImage?: string
    ticketNo?: number | string | null
    /** 嵌在页面里做静态预览：不铺满屏幕、不带背景与按钮 */
    inline?: boolean
    /** 只要票面：去掉出票机、阴影与按钮（个人档案「我的纪念票」复用同一张票） */
    bare?: boolean
    /** 是否显示「撕票根」手势条（档案里只看票，不撕） */
    showTearHandle?: boolean
    /** 一开始就是「已剪开」状态：不显示副券、主票右侧齐平 */
    torn?: boolean
    /** 只显示纪念票图片本身（个人档案用，不带票纸/色条/文字层） */
    imageOnly?: boolean
    /** bare 模式下是否保留右侧副券（个人档案要完整票面） */
    stub?: boolean
  }>(),
  {
    identityLabel: '',
    userName: '',
    joinedAt: '',
    ticketImage: '',
    ticketNo: null,
    inline: false,
    bare: false,
    showTearHandle: true,
    torn: false,
    imageOnly: false,
    stub: false,
  },
)

const emit = defineEmits<{ enter: []; skip: [] }>()

type Phase = 'flying' | 'settled'

const rootRef = ref<HTMLElement | null>(null)
const ticketRef = ref<HTMLElement | null>(null)
const enterRef = ref<HTMLButtonElement | null>(null)
const phase = ref<Phase>('flying')
let settleTimer: ReturnType<typeof setTimeout> | null = null

const ticketImageSrc = useAuthedImage(() => props.ticketImage)
const mainStyle = computed<Record<string, string>>(() => {
  const style: Record<string, string> = {}
  if (ticketImageSrc.value) style['--jt-cover'] = `url("${ticketImageSrc.value}")`
  return style
})

const joinedDate = computed(() => (props.joinedAt ? new Date(props.joinedAt) : new Date()))
const dateText = computed(() => {
  const d = joinedDate.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}.${pad(d.getMonth() + 1)}.${pad(d.getDate())}`
})
/** 票号：比赛内自增，展示成 5 位（00001）；拿不到后端号时退回旧的时间戳编号 */
const ticketNo = computed(() => {
  const raw = props.ticketNo
  if (raw !== null && raw !== undefined && String(raw).trim() !== '') {
    const value = Number(raw)
    if (Number.isFinite(value) && value > 0) return String(Math.trunc(value)).padStart(5, '0')
  }
  return `T${props.competitionId}-${String(joinedDate.value.getTime()).slice(-6)}`
})
const timeText = computed(() => {
  const d = joinedDate.value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${dateText.value} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

/** 身份条形码：由「比赛 + 持有人 + 身份」稳定生成，同一个人/身份图案一致。 */
const identitySignature = computed(
  () =>
    `${props.competitionId}|${props.userName || '参赛代表'}|${props.identityLabel || '参赛代表'}`,
)
const barcodeBars = computed<number[]>(() => {
  const text = identitySignature.value
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  let seed = hash >>> 0
  const next = () => {
    seed ^= seed << 13
    seed >>>= 0
    seed ^= seed >>> 17
    seed ^= seed << 5
    seed >>>= 0
    return seed
  }
  return Array.from({ length: 24 }, (_, index) => ((next() >>> (index % 16)) % 3) + 1)
})

/** 沿虚线向下划一下：把票根从票面上撕下来（archives 里直接以「已剪开」形态展示） */
const torn = ref(props.torn)
const tearing = ref(false)
let tearStartX = 0
let tearStartY = 0

function onTearStart(event: PointerEvent): void {
  if (torn.value) return
  event.preventDefault()
  tearing.value = true
  tearStartX = event.clientX
  tearStartY = event.clientY
  const handle = event.currentTarget as HTMLElement | null
  handle?.setPointerCapture?.(event.pointerId)
}

function onTearMove(event: PointerEvent): void {
  if (!tearing.value || torn.value) return
  const dy = Math.abs(event.clientY - tearStartY)
  const dx = Math.abs(event.clientX - tearStartX)
  // 竖向划够 46px（且没有横向跑偏）就认为撕开了
  if (dy >= 46 && dx <= 80) {
    torn.value = true
    tearing.value = false
  }
}

function onTearEnd(): void {
  tearing.value = false
}

function settle(): void {
  if (phase.value !== 'flying') return
  if (settleTimer) clearTimeout(settleTimer)
  phase.value = 'settled'
  window.setTimeout(() => enterRef.value?.focus(), 60)
}

function scheduleSettle(delay = 2300): void {
  if (settleTimer) clearTimeout(settleTimer)
  settleTimer = setTimeout(settle, delay)
}

function onEnter(): void {
  emit('enter')
}

function onSkip(): void {
  emit('skip')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    onSkip()
    return
  }
  const target = event.target as HTMLElement | null
  if (target?.closest('button')) return
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (phase.value === 'flying') settle()
    else onEnter()
  }
}

/** 直接把页面上的票据截成 PNG，保证导出与页面显示完全一致。 */
async function downloadTicket(): Promise<void> {
  const node = ticketRef.value
  if (!node) return
  const box = node.getBoundingClientRect()
  // 3~4 倍图：小票面也能印得清楚；上限 4 倍，避免超大画布
  const ratio = Math.min(4, Math.max(3, Math.round((window.devicePixelRatio || 1) * 2)))
  const render = (pixelRatio: number) =>
    toPng(node, {
      pixelRatio,
      width: Math.round(box.width),
      height: Math.round(box.height),
      backgroundColor: '#ffffff',
      cacheBust: false,
    })
  try {
    let dataUrl: string
    try {
      dataUrl = await render(ratio)
    } catch {
      // 个别浏览器大画布会失败，退一档重试
      dataUrl = await render(2)
    }
    const safeName = (props.competitionName || '比赛').replace(/[\\/:*?"<>|]/g, '_')
    const anchor = document.createElement('a')
    anchor.href = dataUrl
    anchor.download = `${safeName}-参赛凭证.png`
    anchor.click()
  } catch {
    // 浏览器不支持 SVG foreignObject 时保持静默，不阻断加入流程
  }
}

function onReducedMotion(query: MediaQueryListEvent | MediaQueryList): void {
  if (query.matches) {
    if (settleTimer) clearTimeout(settleTimer)
    phase.value = 'settled'
    window.setTimeout(() => enterRef.value?.focus(), 60)
  }
}

const motionQuery =
  typeof window !== 'undefined' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null

onMounted(() => {
  if (props.bare) {
    phase.value = 'settled'
    return
  }
  if (!props.inline) document.body.style.overflow = 'hidden'
  rootRef.value?.focus()
  if (motionQuery?.matches) {
    phase.value = 'settled'
    window.setTimeout(() => enterRef.value?.focus(), 60)
    return
  }
  motionQuery?.addEventListener('change', onReducedMotion)
  scheduleSettle()
})

onBeforeUnmount(() => {
  if (!props.inline) document.body.style.overflow = ''
  motionQuery?.removeEventListener('change', onReducedMotion)
  if (settleTimer) clearTimeout(settleTimer)
})
</script>

<style scoped>
.jt-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background:
    radial-gradient(65% 52% at 50% 26%, #eef0ff 0%, rgba(246, 247, 251, 0) 72%),
    radial-gradient(45% 45% at 84% 78%, rgba(6, 182, 212, 0.1), transparent 74%),
    var(--color-bg);
  color: var(--color-text-primary);
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
    'Hiragino Sans GB', 'Microsoft YaHei', sans-serif;
  outline: none;
}

.jt-overlay,
.jt-overlay * {
  box-sizing: border-box;
}

/* 只显示票图：不给任何底色/渐变/文字层 */
/* 票图本身可能带透明通道：垫一层白，避免透出页面底色（淡紫） */
.jt-image-only {
  display: block;
  width: 100%;
  max-width: 560px;
  height: auto;
  background: var(--color-surface);
  border-radius: var(--radius-xs);
}

/* 纯票面（个人档案）：按票的原尺寸展示（设计稿 560×292），不撑满整行；不要副券 */
/* 与「加入比赛时那张券」同尺寸（560×330）排版，再整体缩放，比例完全一致 */
.jt-overlay.is-bare .jt-ticket {
  width: 560px;
  max-width: none;
  zoom: 0.78;
  --jt-main-w: 100%;
}

.jt-overlay.is-bare .jt-ticket.has-stub {
  width: 560px;
  zoom: 0.9;
  --jt-main-w: 74%;
}

.jt-overlay.is-bare .jt-ticket.has-stub .jt-main {
  width: 74%;
  flex: 0 0 74%;
  border-radius: var(--radius-lg) 3px 3px var(--radius-lg);
}

.jt-overlay.is-bare .jt-ticket.has-stub .jt-stub {
  width: 26%;
  flex: 0 0 26%;
}

.jt-overlay.is-bare .jt-main {
  transform: none;
  animation: none;
  border-radius: var(--radius-lg) 0 0 var(--radius-lg);
  box-shadow: none;
}

/* 副券保持原样式：左侧 2px 虚线裁口 + 自己的圆角/底色 */
.jt-overlay.is-bare .jt-stub {
  transform: none;
  animation: none;
  box-shadow: none;
}

/* 档案展示的是票本身：底色纯白，但圆角/描边/阴影/顶部彩条沿用参考票 */
.jt-overlay.is-bare .jt-ticket,
.jt-overlay.is-bare .jt-ticket.is-torn {
  background:
    var(--gradient-brand) top center / 100% 4px no-repeat,
    var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: 0 18px 36px -24px rgba(15, 23, 42, 0.35);
}

.jt-overlay.is-bare .jt-main,
.jt-overlay.is-bare .jt-ticket.is-torn .jt-main,
.jt-overlay.is-bare .jt-ticket.is-torn .jt-main.has-image {
  background-color: var(--color-surface);
  /* 彩条交给外层整张票画，主票这里只放票图 */
  background-image: var(--jt-cover);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
  border-radius: var(--radius-xs);
  box-shadow: none;
  animation: none;
  transform: none;
}

/* 没有票图时就是一张白票面，不要淡紫渐变 */
.jt-overlay.is-bare .jt-main:not(.has-image) {
  background-image: none;
}

/* 纯票面（个人档案）：不要出票机、阴影与窗口留白，只保留票本身 */
.jt-overlay.is-bare {
  position: relative;
  inset: auto;
  display: block;
  width: 100%;
  height: auto;
  padding: 0;
  overflow: visible;
  background: var(--color-surface);
}

.jt-overlay.is-bare .jt-printer,
.jt-overlay.is-bare .jt-shadow {
  display: none;
}

.jt-overlay.is-bare .jt-window {
  width: 100%;
  margin: 0;
  padding: 0;
  overflow: visible;
}

.jt-overlay.is-bare .jt-stage {
  width: 100%;
  padding: 0;
}

/* 页面内嵌预览：回到文档流，不要满屏遮罩 */
.jt-overlay.is-inline {
  position: relative;
  inset: auto;
  display: block;
  width: 100%;
  padding: 0;
  overflow: visible;
  background: transparent;
}

.jt-overlay.is-inline .jt-stage {
  width: 100%;
  max-width: 100%;
  padding: 0;
  gap: 0;
  overflow: visible;
}

.jt-overlay.is-inline .jt-machine {
  width: 100%;
  max-width: none;
  overflow: visible;
}

/* 预览里不需要给满屏阴影留负边距，否则票会被卡片裁掉一截 */
.jt-overlay.is-inline .jt-window {
  width: 100%;
  margin: 0;
  padding: 20px 0 24px;
  overflow: visible;
}

.jt-overlay.is-inline .jt-printer {
  width: 100%;
  margin: 0 0 8px;
}

.jt-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.jt-bg-glow {
  position: absolute;
  inset: -30%;
  background:
    radial-gradient(34% 42% at 50% 34%, rgba(99, 102, 241, 0.16), transparent 72%),
    radial-gradient(28% 34% at 18% 76%, rgba(139, 92, 246, 0.1), transparent 74%),
    radial-gradient(30% 34% at 84% 18%, rgba(6, 182, 212, 0.1), transparent 74%);
  filter: blur(12px);
}

.jt-bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(79, 70, 229, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(79, 70, 229, 0.05) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: radial-gradient(60% 60% at 50% 42%, #000 24%, transparent 100%);
  opacity: 0.75;
}

.jt-stage {
  position: relative;
  z-index: 1;
  display: flex;
  width: 100%;
  max-width: 820px;
  padding: 46px 20px 30px;
  flex-direction: column;
  align-items: center;
  gap: 22px;
}

.jt-heading {
  display: flex;
  align-items: center;
  flex-direction: column;
  gap: 7px;
  text-align: center;
  animation: jt-fade-up 0.4s var(--ease-out-expo) both;
}

.jt-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 12px;
  border-radius: var(--radius-full);
  background: var(--color-success-soft);
  color: #15803d;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.jt-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.13);
}

.jt-heading-title {
  margin: 0;
  color: var(--color-text-primary);
  font-size: clamp(21px, 3vw, 26px);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.2;
}

.jt-machine {
  position: relative;
  display: flex;
  width: 100%;
  max-width: 920px;
  justify-content: center;
  align-items: center;
  perspective: 1400px;
}

.jt-shadow {
  position: absolute;
  z-index: 1;
  bottom: -20px;
  left: 50%;
  width: min(480px, 76%);
  height: 26px;
  border-radius: 50%;
  background: radial-gradient(ellipse, rgba(79, 70, 229, 0.22), transparent 70%);
  filter: blur(10px);
  opacity: 0;
  transform: translateX(-50%) scale(0.8);
  pointer-events: none;
}

.jt-machine.is-flying .jt-shadow {
  animation: jt-shadow 2.2s cubic-bezier(0.2, 0.8, 0.2, 1) both;
  bottom: -26px;
}

.jt-ticket-wrap {
  position: relative;
  z-index: 2;
  display: flex;
  width: min(560px, 100%);
  max-width: 100%;
  flex-direction: column;
}

/* ---------- 出票口 ---------- */
.jt-printer {
  position: relative;
  z-index: 3;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  margin: 0 -14px;
  border: 1px solid var(--color-border);
  border-bottom: none;
  border-radius: 16px 16px 0 0;
  background: linear-gradient(180deg, #fbfcff 0%, #eceef8 62%, #e0e3f0 100%);
  box-shadow:
    0 -1px 0 rgba(255, 255, 255, 0.9) inset,
    0 10px 22px -14px rgba(15, 23, 42, 0.45);
}

.jt-printer-led {
  position: absolute;
  top: 11px;
  left: 18px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.16);
  opacity: 0.55;
}

.jt-printer.is-flying .jt-printer-led {
  animation: jt-led 0.72s ease-in-out infinite;
}

.jt-printer-label {
  color: var(--color-text-tertiary);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.32em;
  opacity: 0.8;
}

/* 出票缝：机头底缘的深色缝，票据从它下面出来 */
.jt-printer-slot {
  position: absolute;
  right: 12px;
  bottom: -2px;
  left: 12px;
  height: 7px;
  border-radius: 0 0 6px 6px;
  background: linear-gradient(180deg, #2b3040 0%, #11141c 100%);
  box-shadow:
    0 2px 4px rgba(15, 23, 42, 0.35) inset,
    0 1px 0 rgba(255, 255, 255, 0.7);
}

/* 出票窗口：上沿贴着出票缝，超出的部分裁掉，看着就是从缝里出来 */
/* 出票窗口：只有出票动画进行时才裁切，票落定后完全放开，
   否则撕下来的票根旋转/位移后会被窗口边缘切掉一角 */
.jt-window {
  position: relative;
  z-index: 2;
  margin: 0 -72px -84px;
  /* 顶部留白 = 出票后票面与出票口之间的距离 */
  padding: 20px 72px 84px;
  overflow: visible;
}

.jt-window.is-flying {
  overflow: hidden;
}

.jt-ticket {
  position: relative;
  display: flex;
  width: 100%;
  max-width: 100%;
  aspect-ratio: 560 / 292;
  min-height: 250px;
  overflow: visible;
  --jt-main-w: 74%;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background:
    var(--gradient-brand) top center / 100% 4px no-repeat,
    linear-gradient(135deg, #ffffff 0%, #fdfdfe 56%, #f4f5ff 100%);
  color: var(--color-text-primary);
  box-shadow:
    var(--shadow-xl),
    0 0 0 1px rgba(255, 255, 255, 0.7) inset;
  user-select: none;
  -webkit-user-select: none;
}

.jt-ticket.is-flying {
  animation: jt-eject 2.2s cubic-bezier(0.22, 0.86, 0.24, 1) both;
}

.jt-ticket::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 4;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(79, 70, 229, 0.08);
  pointer-events: none;
}

.jt-ticket.has-image .jt-gloss {
  display: none;
}

.jt-gloss {
  position: absolute;
  inset: 0;
  z-index: 1;
  border-radius: var(--radius-lg);
  background: radial-gradient(70% 100% at 88% 0, rgba(99, 102, 241, 0.1), transparent 58%);
  opacity: 0.9;
  pointer-events: none;
}

/* 虚线处的撕票把手：透明感应区，悬停给一点提示 */
.jt-tear-handle {
  position: absolute;
  z-index: 6;
  top: 0;
  bottom: 0;
  left: var(--jt-main-w);
  width: 34px;
  transform: translateX(-50%);
  cursor: grab;
  touch-action: none;
}

.jt-tear-handle::after {
  content: '';
  position: absolute;
  top: 8%;
  bottom: 8%;
  left: 50%;
  width: 2px;
  transform: translateX(-50%);
  background: repeating-linear-gradient(
    180deg,
    rgba(79, 70, 229, 0.5) 0 6px,
    transparent 6px 12px
  );
  opacity: 0;
  transition: opacity var(--dur-fast, 0.15s) ease;
}

.jt-tear-handle:hover::after,
.jt-tear-handle.is-active::after {
  opacity: 1;
}

.jt-tear-handle.is-active {
  cursor: grabbing;
}

/* 撕开：票面与票根各自成一张卡，向两边分开 */
.jt-ticket.is-torn {
  background: none;
  box-shadow: none;
}

.jt-ticket.is-torn::after {
  display: none;
}

.jt-ticket.is-torn .jt-gloss {
  display: none;
}

/* 撕开后的主票：顶部色条 + 图片（同样不压遮罩） */
.jt-ticket.is-torn .jt-main.has-image {
  background-image: var(--gradient-brand), var(--jt-cover);
  background-position: top center, center;
  background-size: 100% 4px, cover;
  background-repeat: no-repeat, no-repeat;
}

/* 剪掉副券后：主票右侧是齐平的裁切口 */
.jt-ticket.is-torn .jt-main {
  transform: none;
  border-radius: var(--radius-lg) 0 0 var(--radius-lg);
  background:
    var(--gradient-brand) top center / 100% 4px no-repeat,
    linear-gradient(135deg, #ffffff 0%, #fdfdfe 56%, #f4f5ff 100%);
  box-shadow: 0 18px 36px -24px rgba(15, 23, 42, 0.5);
  animation: jt-tear-main 0.62s cubic-bezier(0.22, 0.86, 0.24, 1) both;
}

.jt-ticket.is-torn .jt-stub {
  border-left-color: transparent;
  border-radius: 3px var(--radius-lg) var(--radius-lg) 3px;
  background: linear-gradient(160deg, #fbfbff, #eef0fb);
  box-shadow: 0 18px 36px -24px rgba(15, 23, 42, 0.45);
  animation: jt-tear-stub 0.74s cubic-bezier(0.22, 0.86, 0.24, 1) both;
}

@keyframes jt-tear-main {
  0% {
    transform: none;
  }
  40% {
    transform: translate(min(-10px, -1.2vw), 4px) rotate(-1.1deg);
  }
  /* 撕完落平：票面最终是水平、右对齐的裁切口，不留倾斜 */
  100% {
    transform: none;
  }
}

@keyframes jt-tear-stub {
  0% {
    transform: none;
  }
  26% {
    transform: translate(min(12px, 1.6vw), -3px) rotate(2.2deg);
  }
  100% {
    transform: translate(min(36px, 3.6vw), 16px) rotate(7deg);
  }
}

.jt-main.has-image {
  background-image: var(--jt-veil), var(--jt-cover);
  background-position: center, center;
  background-size: cover, cover;
  background-repeat: no-repeat, no-repeat;
}

.jt-main {
  position: relative;
  z-index: 2;
  display: flex;
  width: var(--jt-main-w);
  min-width: 0;
  padding: clamp(16px, 2.6vw, 22px) clamp(16px, 2.8vw, 24px);
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
}

/* 没传纪念票图时：留白但加一点柔和底色，不至于像空白 */
.jt-main:not(.has-image) {
  background-image:
    radial-gradient(120% 90% at 18% 0%, rgba(99, 102, 241, 0.07), transparent 62%),
    linear-gradient(135deg, #ffffff 0%, #fdfdfe 56%, #f4f5ff 100%);
  background-position: center, center;
  background-size: cover, cover;
  background-repeat: no-repeat, no-repeat;
}

/* 有纪念票图时：主票就是那张图，不再压深色遮罩，靠文字描边保证可读 */
.jt-main.has-image {
  background-image: var(--jt-cover);
  background-position: center;
  background-size: cover;
  background-repeat: no-repeat;
}

.jt-main.has-image .jt-brand,
.jt-main.has-image .jt-main-name,
.jt-main.has-image .jt-main-time,
.jt-main.has-image .jt-main-no {
  color: #ffffff;
  /* 一圈轮廓：四个斜向 + 上下左右 的描边，加上一层柔和投影 */
  text-shadow:
    -0.7px -0.7px 0 rgba(9, 14, 30, 0.8),
    0.7px -0.7px 0 rgba(9, 14, 30, 0.8),
    -0.7px 0.7px 0 rgba(9, 14, 30, 0.8),
    0.7px 0.7px 0 rgba(9, 14, 30, 0.8),
    -0.7px 0 0 rgba(9, 14, 30, 0.65),
    0.7px 0 0 rgba(9, 14, 30, 0.65),
    0 -0.7px 0 rgba(9, 14, 30, 0.65),
    0 0.7px 0 rgba(9, 14, 30, 0.65),
    0 2px 8px rgba(3, 7, 18, 0.5);
}


.jt-main-foot {
  display: grid;
  min-width: 0;
  padding-top: 10px;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'name no'
    'time no';
  align-items: end;
  gap: 2px 12px;
}

.jt-main-name {
  grid-area: name;
}

.jt-main-time {
  grid-area: time;
}

/* 主票右下角的票号数字 */
.jt-main-no {
  grid-area: no;
  align-self: end;
  padding-bottom: 2px;
  color: var(--color-text-tertiary);
  font-size: clamp(8px, 1vw, 10px);
  font-weight: 500;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.jt-main-name {
  overflow: hidden;
  color: var(--color-text-primary);
  font-size: clamp(13px, 1.8vw, 17px);
  font-weight: 700;
  letter-spacing: -0.01em;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.jt-main-time {
  color: var(--color-text-secondary);
  font-size: clamp(7px, 1.05vw, 9px);
  letter-spacing: 0.03em;
}

.jt-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.jt-brand {
  color: var(--color-primary);
  font-size: clamp(9px, 1.4vw, 11px);
  font-weight: 600;
  letter-spacing: 0.08em;
}

.jt-pass {
  color: var(--color-text-tertiary);
  font-size: clamp(7px, 1.2vw, 9px);
  letter-spacing: 0.14em;
}

.jt-meta {
  display: grid;
  margin: clamp(12px, 2.4vw, 20px) 0 0;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 18px;
}

.jt-meta div {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: 8px;
}

.jt-meta dt {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
  font-size: clamp(9px, 1.3vw, 11px);
  letter-spacing: 0.06em;
}

.jt-meta dd {
  margin: 0;
  overflow: hidden;
  color: var(--color-text-primary);
  font-size: clamp(11px, 1.7vw, 14px);
  font-weight: 600;
  letter-spacing: -0.01em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jt-stub {
  position: relative;
  z-index: 2;
  display: flex;
  width: calc(100% - var(--jt-main-w));
  padding: clamp(12px, 2vw, 18px) clamp(8px, 1.4vw, 12px);
  align-items: flex-start;
  flex-direction: column;
  gap: 3px;
  border-left: 2px dashed rgba(79, 70, 229, 0.2);
  border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
  background: linear-gradient(160deg, rgba(99, 102, 241, 0.07), rgba(6, 182, 212, 0.05));
}

.jt-stub-label {
  padding-bottom: 2px;
  color: var(--color-primary);
  font-size: clamp(9px, 1.4vw, 11px);
  font-weight: 700;
  letter-spacing: 0.24em;
}

.jt-barcode {
  display: flex;
  width: 100%;
  height: 34px;
  margin-top: auto;
  align-items: stretch;
  justify-content: space-between;
  gap: 1.5px;
}

.jt-barcode i {
  display: block;
  background: var(--color-text-primary);
}

.jt-stub-no {
  color: var(--color-text-tertiary);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 8px;
  letter-spacing: 0.04em;
}

.jt-status {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--color-text-secondary);
  font-size: 12px;
  letter-spacing: 0.06em;
}

.jt-status::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.12);
  animation: jt-pulse 1.2s ease-in-out infinite;
}

.jt-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  animation: jt-fade-up 0.3s var(--ease-out-expo) both;
}

.jt-btn {
  min-height: 42px;
  padding: 0 20px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-full);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.01em;
  box-shadow: var(--shadow-xs);
  cursor: pointer;
  transition:
    transform 0.12s ease,
    border-color 0.15s ease,
    color 0.15s ease,
    box-shadow 0.15s ease;
}

.jt-btn:hover {
  border-color: rgba(79, 70, 229, 0.38);
  color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.jt-btn:active {
  transform: scale(0.98);
}

.jt-btn:focus-visible {
  outline: 2px solid rgba(var(--color-primary-rgb), 0.55);
  outline-offset: 3px;
}

.jt-btn--primary {
  border-color: transparent;
  background: var(--gradient-brand);
  color: #ffffff;
  font-weight: 600;
  box-shadow: var(--shadow-glow-sm);
}

.jt-btn--primary:hover {
  border-color: transparent;
  background: var(--gradient-brand-hover);
  color: #ffffff;
  box-shadow: var(--shadow-glow);
}


/* 出票：从出票缝里匀速往外推，末端带一点纸张的顿挫感 */
@keyframes jt-eject {
  0% {
    transform: translateY(-102%);
  }
  18% {
    transform: translateY(-74%);
  }
  42% {
    transform: translateY(-34%);
  }
  62% {
    transform: translateY(-3%);
  }
  72% {
    transform: translateY(1.4%) rotate(0.35deg);
  }
  84% {
    transform: translateY(-0.6%) rotate(-0.2deg);
  }
  100% {
    transform: translateY(0) rotate(0);
  }
}

@keyframes jt-led {
  0%,
  100% {
    opacity: 0.35;
    box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.1);
  }
  50% {
    opacity: 1;
    box-shadow: 0 0 0 5px rgba(34, 197, 94, 0.22);
  }
}

@keyframes jt-shadow {
  0% {
    opacity: 0;
    transform: translateX(-42%) scale(0.55);
  }
  18% {
    opacity: 0.45;
    transform: translateX(-58%) scale(0.75);
  }
  54% {
    opacity: 0.55;
    transform: translateX(-50%) scale(1.02);
  }
  78% {
    opacity: 0.3;
    transform: translateX(-50%) scale(0.94);
  }
  100% {
    opacity: 0.2;
    transform: translateX(-50%) scale(0.9);
  }
}

@keyframes jt-fade-up {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes jt-pulse {
  0%,
  100% {
    opacity: 0.55;
    transform: scale(0.9);
  }
  50% {
    opacity: 1;
    transform: scale(1.15);
  }
}

.jt-ticket {
  aspect-ratio: 560 / 330;
  min-height: 280px;
}

.jt-info {
  display: grid;
  width: 100%;
  /* 和上面「副券」标题拉开距离 */
  margin: clamp(18px, 3vw, 28px) 0 0;
  padding: 0;
  grid-template-columns: 1fr;
  gap: 6px;
  border: none;
  background: none;
}

.jt-info > div {
  display: flex;
  min-width: 0;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.jt-info dt {
  flex: 0 0 auto;
  color: var(--color-text-secondary);
  font-size: clamp(8px, 1.2vw, 10px);
  letter-spacing: 0.04em;
}

.jt-info dd {
  margin: 0;
  overflow: hidden;
  color: var(--color-text-primary);
  font-size: clamp(8px, 1.25vw, 11px);
  font-weight: 600;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.jt-info .jt-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: clamp(10px, 1.5vw, 12px);
  font-weight: 500;
  letter-spacing: 0.02em;
}

@media (max-width: 640px) {
  .jt-stage {
    padding: 54px 14px 22px;
    gap: 18px;
  }

  .jt-heading {
    gap: 6px;
  }

  .jt-ticket {
    aspect-ratio: 520 / 370;
    min-height: 0;
  }

  .jt-info {
    gap: 5px;
  }

  .jt-info dd {
    font-size: 10px;
  }

  .jt-info .jt-mono {
    font-size: 9px;
  }

  .jt-ticket {
    --jt-main-w: 70%;
  }

  .jt-main {
    padding: 14px;
    min-width: 0;
  }

  .jt-meta {
    grid-template-columns: 1fr;
    gap: 5px;
  }

  .jt-meta dd {
    font-size: 12px;
  }

  .jt-stub {
    padding: 12px 10px;
  }

  .jt-shadow {
    bottom: -14px;
    height: 18px;
  }

  .jt-actions {
    flex-wrap: wrap;
    justify-content: center;
  }

  .jt-btn {
    min-height: 40px;
    padding: 0 18px;
  }
}

@media (max-width: 680px) {
  .jt-ticket.is-torn .jt-stub {
    animation-name: jt-tear-stub-sm;
  }
  .jt-ticket.is-torn .jt-main {
    animation-name: jt-tear-main-sm;
  }
}

@keyframes jt-tear-stub-sm {
  0% {
    transform: none;
  }
  26% {
    transform: translate(0, 4px) rotate(1.6deg);
  }
  100% {
    transform: translate(2px, 26px) rotate(3.6deg);
  }
}

@keyframes jt-tear-main-sm {
  0% {
    transform: none;
  }
  100% {
    transform: translate(-6px, 6px) rotate(-1.2deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .jt-ticket.is-torn .jt-main,
  .jt-ticket.is-torn .jt-stub {
    animation-duration: 0.01s;
  }

  .jt-ticket.is-flying,
  .jt-machine.is-flying .jt-shadow,
  .jt-status::before,
  .jt-heading,
  .jt-actions {
    animation: none;
  }
}
</style>
