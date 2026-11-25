import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueJsx from '@vitejs/plugin-vue-jsx'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
// 开发代理目标可用 env 覆盖（默认本机 8000/8001），见 .env.example：
//   VITE_API_TARGET=http://localhost:8000
//   VITE_WS_TARGET=ws://localhost:8001

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const API_TARGET = env.VITE_API_TARGET || 'http://localhost:8000'
  const WS_TARGET = env.VITE_WS_TARGET || 'ws://localhost:8001'
  return {
  plugins: [
    vue(),
    vueJsx(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 开发代理：/api → waitress WSGI（多线程，实测并发 ~910 QPS）；
    // /ws → daphne ASGI（WebSocket；Django 同步视图在 ASGI 下单线程执行，故 HTTP 不走它）
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
      '/ws': {
        target: WS_TARGET,
        ws: true,
      },
    },
  },
  }
})
