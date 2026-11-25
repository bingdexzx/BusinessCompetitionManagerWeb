import { fileURLToPath } from 'node:url'
import type { UserConfig } from 'vite'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config.ts'

// vite.config 现在是「函数形式」（为了读 .env 的 mode），vitest 合并时需要先调用它
const baseConfig: UserConfig =
  typeof viteConfig === 'function'
    ? (viteConfig as (env: { mode: string; command: string }) => UserConfig)({
        mode: 'test',
        command: 'serve',
      })
    : viteConfig

export default mergeConfig(
  baseConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      root: fileURLToPath(new URL('./', import.meta.url)),
    },
  }),
)
