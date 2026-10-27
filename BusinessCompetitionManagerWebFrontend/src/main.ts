import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'
import { setUnauthorizedHandler } from './api/client'
import { useAuthStore } from './stores/auth'
import './assets/styles/global.scss'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 401 且 refresh 失败：清空会话并跳转登录页（中文提示原因，避免“突然跳走”）
setUnauthorizedHandler(() => {
  const auth = useAuthStore(pinia)
  auth.clearSession()
  const current = router.currentRoute.value
  ElMessage.warning('登录已过期，请重新登录')
  if (current.name !== 'login') {
    void router.push({ name: 'login', query: { redirect: current.fullPath } })
  }
})

// 有 token 时恢复当前用户信息（并发去重：路由守卫也会 await 同一次会话补齐）
void useAuthStore(pinia).ensureSession()

// ---------- 全局异常兜底（中文提示 + 防刷屏） ----------
// 渲染/生命周期/侦听器未被捕获的异常、未处理的 Promise 拒绝：统一中文提示，
// 原始错误进控制台便于排查；5 秒内只弹一次，避免错误风暴刷屏。
import { ElMessage } from 'element-plus'
import { errorMessage } from './utils/errors'

let lastGlobalErrorAt = 0
function showGlobalError(err: unknown, fallback: string): void {
  console.error('[全局异常]', err)
  const now = Date.now()
  if (now - lastGlobalErrorAt < 5000) return
  lastGlobalErrorAt = now
  ElMessage.error(errorMessage(err, fallback))
}

app.config.errorHandler = (err) => {
  showGlobalError(err, '页面渲染异常，请刷新后重试')
}
window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
  showGlobalError(e.reason, '操作未完成，请刷新后重试')
})

app.mount('#app')
