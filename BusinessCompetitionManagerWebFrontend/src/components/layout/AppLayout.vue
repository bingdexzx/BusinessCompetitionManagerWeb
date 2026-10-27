<template>
  <div
    class="app-layout"
    :class="{ 'app-layout--drawer': isCompact, 'app-layout--nav-open': mobileNavOpen }"
  >
    <!-- 顶部品牌渐变细条（旧产品同款视觉） -->
    <div class="app-accent"></div>
    <Sidebar :drawer="isCompact" :open="mobileNavOpen" />
    <!-- 抽屉模式下的遮罩：点击关闭侧栏；仅在平板/手机且抽屉打开时出现 -->
    <div
      v-show="isCompact && mobileNavOpen"
      class="sidebar-backdrop"
      @click="mobileNavOpen = false"
    ></div>
    <div class="app-main">
      <TopBar :show-menu-toggle="isCompact" @toggle="mobileNavOpen = !mobileNavOpen" />
      <div ref="contentRef" class="app-content">
        <div class="route-wrap">
          <!-- 其他视图的页面内容统一渲染在此处 -->
          <slot />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './Sidebar.vue'
import TopBar from './TopBar.vue'
import {
  subscribeCompetition,
  subscribeGlobal,
  unsubscribeCompetition,
} from '@/composables/useNotifications'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const auth = useAuthStore()

// 平板/手机下侧栏为抽屉模式，默认收起；由顶栏汉堡按钮或路由切换控制开关。
const mobileNavOpen = ref(false)

// 响应式断点（≤1024px 抽屉模式），与 variables.scss 的断点保持一致
const isCompact = ref(false)
let mql: MediaQueryList | null = null

function onMediaChange(e: MediaQueryList | MediaQueryListEvent): void {
  isCompact.value = e.matches
}

onMounted(() => {
  mql = window.matchMedia('(max-width: 1024px)')
  isCompact.value = mql.matches
  mql.addEventListener('change', onMediaChange)
})

onBeforeUnmount(() => {
  mql?.removeEventListener('change', onMediaChange)
})

// 切换路由（含点击菜单项）后自动收起抽屉，避免遮挡新页面
watch(
  () => route.fullPath,
  () => {
    mobileNavOpen.value = false
  },
)

// 切换页面后滚动回顶部：内容滚动容器是 .app-content（不是 window），
// 否则从长列表进入下一页会停在半空，像是「信息断了一截」。
// 用瞬时归零（不做平滑滚动）：跨页长距离动画会让人失去位置感。
const contentRef = ref<HTMLElement | null>(null)
watch(
  () => route.path,
  (_to, from) => {
    if (!from) return
    const el = contentRef.value
    if (el) el.scrollTop = 0
  },
)
// 放大回桌面尺寸时强制收起，恢复固定侧栏布局
watch(isCompact, (compact) => {
  if (!compact) mobileNavOpen.value = false
})

// 系统级资源变更订阅（全局库）：登录后常驻，任何页面都能收到全局广播
subscribeGlobal()

// 进入 /competitions/:cid/... 页面时同步当前比赛上下文（API 请求头 X-Competition-Id 依赖它），
// 并**集中订阅该比赛的资源变更广播**——这样每个比赛页面都无需各自订阅即可实时同步。
let subscribedCid = ''
watch(
  () => route.params.cid,
  (cid) => {
    // 只接受纯数字 id：拦截 undefined/null/非法值污染上下文（曾致 /competitions/undefined 请求）
    if (typeof cid !== 'string' || !/^\d+$/.test(cid)) return
    auth.selectCompetition(cid)
    if (subscribedCid && subscribedCid !== cid) unsubscribeCompetition(subscribedCid)
    subscribedCid = cid
    subscribeCompetition(cid)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (subscribedCid) unsubscribeCompetition(subscribedCid)
})
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh; /* 回退：老浏览器不支持 dvh 时仍可用 */
  height: 100dvh; /* 移动端动态视口高度：避开地址栏导致底部被裁切、内容不可达 */
  overflow: hidden;
  position: relative;
}
.app-accent {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--gradient-brand);
  z-index: 100;
}
.app-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-bg);
  position: relative;
}
/* 抽屉遮罩：覆盖主区与顶栏，置于抽屉之下、内容之上。仅抽屉模式启用过渡。 */
.sidebar-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  opacity: 0;
  transition: opacity var(--dur-base) var(--ease-out-expo);
}
.app-layout--nav-open .sidebar-backdrop {
  opacity: 1;
}
/* 抽屉模式下，打开时锁定 body 滚动（与抽屉滑入同步） */
.app-layout--drawer.app-layout--nav-open {
  overflow: hidden;
}
/* 主区角落的品牌光晕（旧产品同款氛围装饰） */
.app-main::before {
  content: "";
  position: absolute;
  top: -160px;
  right: -120px;
  width: 420px;
  height: 420px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.08), rgba(6, 182, 212, 0) 70%);
  pointer-events: none;
  z-index: 0;
  animation: glow-drift 20s ease-in-out infinite alternate;
}
.app-main::after {
  content: "";
  position: absolute;
  bottom: -180px;
  left: 200px;
  width: 380px;
  height: 380px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.06), rgba(139, 92, 246, 0) 70%);
  pointer-events: none;
  z-index: 0;
  animation: glow-drift 25s ease-in-out infinite alternate-reverse;
}
@keyframes glow-drift {
  0% {
    transform: translate(0, 0) scale(1);
  }
  100% {
    transform: translate(30px, 20px) scale(1.1);
  }
}
.app-content {
  position: relative;
  z-index: 1;
  flex: 1;
  overflow: auto;
  -webkit-overflow-scrolling: touch; /* iOS 惯性滚动 */
  overscroll-behavior: contain; /* 避免连锁触发外层滚动/下拉刷新 */
  padding: var(--content-padding);
}
.route-wrap {
  width: 100%;
  min-height: 100%;
  /* flex 列容器：让直接子页面可用 flex:1 真正撑满 */
  display: flex;
  flex-direction: column;
}
</style>
