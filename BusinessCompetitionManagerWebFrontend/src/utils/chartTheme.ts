/**
 * 行情图表配色（ECharts canvas 无法解析 CSS 变量，统一在这里维护）。
 * 口径与 CSS 令牌一致：红涨绿跌（A 股），深色图表底属刻意反色面板。
 */
export const CHART_THEME = {
  bg: '#1a1a2e',
  panelBg: '#16162a',
  grid: '#2a2a3e',
  axisText: '#8a8a9a',
  tooltipBg: '#3a3a4e',
  tooltipText: '#ffffff',
  pointerLine: '#555555',
  handle: '#4a4a6a',
  up: '#ec0000',
  down: '#00a800',
  ma5: '#f5a623',
  ma10: '#4b83c1',
  ma20: '#e5484d',
} as const
