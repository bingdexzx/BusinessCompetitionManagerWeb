<script setup lang="ts">
// 比赛包导入报告可视化（§13「导入报告可视化」）：
// 成功 / 422 失败共用同一报告结构，历史记录展开也复用本组件。
import { computed } from 'vue'
import type { ImportReport } from '@/api/types'
import { toDisplay } from '@/utils/format'

const props = defineProps<{ report: ImportReport | null }>()

/** 基础数据表格中文名（sheetKey -> 名称） */
const BASEDATA_LABELS: Record<string, string> = {
  fuels: '燃料',
  warehouses: '仓库',
  vehicles: '载具',
  maps: '地图',
  materials: '原料',
  products: '产品',
  parts: '零件',
  infrastructures: '基建',
  tech_tree: '科技树',
  production_lines: '生产线',
}

const isSuccess = computed(() => props.report?.status === 'SUCCESS')

/** 导入耗时（startedAt -> finishedAt） */
const durationText = computed(() => {
  const r = props.report
  if (!r?.startedAt || !r?.finishedAt) return '—'
  const ms = new Date(r.finishedAt).getTime() - new Date(r.startedAt).getTime()
  if (Number.isNaN(ms) || ms < 0) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
})

const basedataEntries = computed(() => {
  const rows = props.report?.basedataRows ?? {}
  return Object.entries(rows).map(([key, count]) => ({
    key,
    label: BASEDATA_LABELS[key] ?? key,
    count,
  }))
})

function shortSha(sha: string | null | undefined): string {
  if (!sha) return '—'
  return sha.slice(0, 12)
}
</script>

<template>
  <div v-if="report" class="import-report">
    <!-- 状态大徽标 + 概要 -->
    <div class="report-summary">
      <span class="report-status" :class="isSuccess ? 'report-status-success' : 'report-status-failed'">
        {{ isSuccess ? '导入成功' : '导入失败' }}
      </span>
      <span class="muted">耗时：{{ durationText }}</span>
      <span class="muted">
        建库：{{ report.createdDatabase || '未创建数据库' }}
      </span>
      <span class="muted">合同实例：{{ report.contractsCreated ?? 0 }}</span>
    </div>

    <!-- 顶层 errors / warnings -->
    <div v-if="report.errors?.length" class="notice notice-error">
      <strong>错误（{{ report.errors.length }}）</strong>
      <ul class="report-list">
        <li v-for="(err, i) in report.errors" :key="`err-${i}`">{{ err }}</li>
      </ul>
    </div>
    <div v-if="report.warnings?.length" class="notice notice-warning">
      <strong>警告（{{ report.warnings.length }}）</strong>
      <ul class="report-list">
        <li v-for="(warn, i) in report.warnings" :key="`warn-${i}`">{{ warn }}</li>
      </ul>
    </div>

    <!-- 插件清单 -->
    <section class="report-section">
      <h3>插件清单（{{ report.plugins?.length ?? 0 }}）</h3>
      <div v-if="report.plugins?.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>文件</th>
              <th>Key</th>
              <th>类型</th>
              <th>版本</th>
              <th>SHA-256</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(plugin, i) in report.plugins" :key="`plugin-${i}`">
              <td>{{ plugin.file }}</td>
              <td>{{ plugin.key }}</td>
              <td>
                <span class="pill" :class="plugin.kind === 'CONTRACT' ? 'pill-blue' : 'pill-green'">
                  {{ plugin.kind }}
                </span>
              </td>
              <td>{{ plugin.version || '—' }}</td>
              <td :title="plugin.sha256">{{ shortSha(plugin.sha256) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">本次未导入插件</p>
    </section>

    <!-- 字段迁移摘要 -->
    <section class="report-section">
      <h3>字段迁移摘要（{{ report.fieldMigrations?.length ?? 0 }}）</h3>
      <div v-if="report.fieldMigrations?.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>产业类型</th>
              <th>新增字段</th>
              <th>更新字段</th>
              <th>字段总数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, i) in report.fieldMigrations" :key="`fm-${i}`">
              <td>{{ m.industryKey }}</td>
              <td class="success-text">+{{ m.added }}</td>
              <td>~{{ m.updated }}</td>
              <td>{{ m.total }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">无字段迁移</p>
    </section>

    <!-- 基础数据行数 -->
    <section class="report-section">
      <h3>基础数据导入</h3>
      <div v-if="basedataEntries.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>数据表</th>
              <th>Sheet</th>
              <th>导入行数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in basedataEntries" :key="entry.key">
              <td>{{ entry.label }}</td>
              <td class="muted">{{ entry.key }}</td>
              <td>{{ entry.count }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">无基础数据导入</p>
    </section>

    <!-- 表格文件明细 -->
    <section class="report-section">
      <h3>表格文件明细（{{ report.files?.length ?? 0 }}）</h3>
      <div v-if="report.files?.length" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>文件</th>
              <th>阶段</th>
              <th>行数</th>
              <th>错误</th>
              <th>警告</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="(file, i) in report.files" :key="`file-${i}`">
              <tr>
                <td>{{ file.file }}</td>
                <td>{{ file.stage }}</td>
                <td>{{ file.rows }}</td>
                <td>
                  <span v-if="file.errors?.length" class="error-text">{{ file.errors.length }} 条</span>
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  <span v-if="file.warnings?.length" class="warning-text">{{ file.warnings.length }} 条</span>
                  <span v-else class="muted">—</span>
                </td>
              </tr>
              <tr v-if="file.errors?.length || file.warnings?.length" class="report-file-detail">
                <td colspan="5">
                  <ul v-if="file.errors?.length" class="report-list">
                    <li v-for="(err, j) in file.errors" :key="`fe-${i}-${j}`" class="error-text">{{ err }}</li>
                  </ul>
                  <ul v-if="file.warnings?.length" class="report-list">
                    <li v-for="(warn, j) in file.warnings" :key="`fw-${i}-${j}`" class="warning-text">
                      {{ warn }}
                    </li>
                  </ul>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">无表格文件明细</p>
    </section>

    <!-- 原始报告兜底（调试用） -->
    <details class="report-raw">
      <summary>原始报告 JSON</summary>
      <pre>{{ toDisplay(report) }}</pre>
    </details>
  </div>
  <p v-else class="empty">暂无导入报告</p>
</template>
