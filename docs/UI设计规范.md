# 《UI 设计与动效规范》v1.0

> 2026-10 全量 UI 优化落地后形成的约定。目标：**信息按类型选展示方式**、**动效精致克制**、
> 新增页面不必再从零发明样式。
>
> 相关文件：
> - 设计变量：[`variables.scss`](../BusinessCompetitionManagerWebFrontend/src/assets/styles/variables.scss)
> - 全局原语：[`global.scss`](../BusinessCompetitionManagerWebFrontend/src/assets/styles/global.scss)
> - 动效工具：[`useMotion.ts`](../BusinessCompetitionManagerWebFrontend/src/composables/useMotion.ts)
> - 页面转场与滚动复位：[`App.vue`](../BusinessCompetitionManagerWebFrontend/src/App.vue)、[`AppLayout.vue`](../BusinessCompetitionManagerWebFrontend/src/components/layout/AppLayout.vue)

---

## 1. 三条硬规矩

1. **不改业务逻辑换外观**：动效与版式调整不得触碰 API 调用、权限判断、校验、实时同步 watcher、业务文案信息量。
2. **不发明新颜色/新圆角/新阴影**：只用 `variables.scss` 里的 `--color-*`、`--radius-*`、`--shadow-*`。
3. **一切动画必须服从 `prefers-reduced-motion`**：全局 CSS 已兜底（见 §5），JS 动画必须自己判断（`useCountUp`/`useFlash` 已内置）。

---

## 2. 信息展示方式选择表

| 信息类型 | 特征 | 展示方式 | 原语 |
|---|---|---|---|
| 关键指标（1–6 个） | 需要一眼看到、会变化 | **指标卡**一排 | `.metric-grid` + `.metric-card`/`.metric-label`/`.metric-value`/`.metric-unit`/`.metric-delta`，配 `useCountUp` |
| 高密度可比数据 | 多列、需横向对比 | **表格**（不卡片化） | `el-table`；数字列右对齐 + `.value-num`；状态列语义色；长表加 `class="table--sticky-head"` |
| 实体详情 | 字段多、分组明显 | **分区 + 描述列表** | `.section-title` 分组；`el-descriptions`；关键数值 `.metric-card`；底部操作 `.sticky-actions` |
| 日志 / 审计 / 时间序列 | 时间为主线 | **时间线或紧凑表格** | 时间列 `.value-num`；筛选收成一条工具条 |
| 首页/入口导航 | 少量入口、需要说明 | **分区卡片 + 一句说明 + 记录数** | `.hover-lift` + `.anim-stagger` |
| 加载中 | 首次进入 / 切比赛 | **骨架屏**（避免空白闪跳） | `.skeleton` / `.skeleton-line` / `.skeleton-card` |
| 空数据 | 无记录 | **空态** | `el-empty`（手机卡片列表用 `MobileCards` 自带空态） |
| 错误 | 请求失败 | 就地提示，不整页崩 | `errorMessage(err, '…')` |

**判断口诀**：能比较的横向排（表格），要强调的放大排（指标卡），要看细节的分区排（详情），
时间为主线的按时间排（时间线）。

---

## 3. 动效刻度（精致克制）

| 场景 | 时长 | 位移 | 缓动 |
|---|---|---|---|
| 交互反馈（hover / press / focus） | `--dur-fast` (160ms) | 0–2px | `--ease-standard` |
| 元素入场（卡片、列表项） | `--dur-base`~`--dur-slow` (240–400ms) | 8–16px | `--ease-out-expo` |
| 页面转场 | 离场 120ms / 入场 280ms | 12px | `--ease-out-expo` |
| 数值滚动 | 600ms | — | easeOutExpo |
| 强调（新增项落位） | ≤400ms | ≤16px | `--ease-spring`（**仅此场景**） |

**禁止**：无限循环的装饰动画（背景光晕属历史保留，不再新增）、大幅位移/旋转/翻转、
对表格行做逐行位移动画（行数可能上千）、让用户等待的"仪式感"动画。

### 现成类

| 类 | 用途 |
|---|---|
| `.anim-fade-in-up` | 单块内容入场 |
| `.anim-stagger` | 列表/网格交错入场（父级加，前 12 个子元素自动错峰） |
| `.hover-lift` | 可交互卡片悬停轻抬 |
| `.pressable` | 可点击元素按下微缩 + 键盘焦点环 |
| `.flash-updated` | 实时数据被推送更新时闪一下（配 `useFlash`） |
| `.page-shift-root` | 页面转场宿主（**由 App.vue 统一提供，页面不要再写页面级转场**） |

### JS 动效

```ts
import { useCountUp, useFlash } from '@/composables/useMotion'

// 数值滚动（首次不播动画，减少动态效果下直接到位）
const shown = useCountUp(score, { precision: 2 })

// 实时更新闪烁
const { flashing, flash } = useFlash()
watch(() => row.value, flash)
```

---

## 4. 布局与无障碍

- **滚动容器是 `.app-content` 而非 window**：页面内**不要**自己监听 `window.scroll`；需要滚动复位靠路由切换（已内置）。
- 键盘可达：交互元素用 `<button>`/`el-button` 或加 `tabindex="0"` + 键盘事件；全局 `:focus-visible` 焦点环已提供。
- 颜色对比：语义色只用于表达状态（成功/警告/危险/信息），不要用颜色作为**唯一**信息通道（配文字或图标）。
- 弹窗必须带 `append-to-body`（本项目布局含 `backdrop-filter`，会破坏 `position: fixed`）。
- 手机断点：≤1024 平板（侧栏转抽屉）、≤640 手机；表格用 `MobileCards` 降级，保持 `SearchToggle` 收纳搜索。

---

## 5. 减少动态效果

`global.scss` 末尾统一兜底：

```scss
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-delay: 0ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

只压缩时长、不移除属性——依赖 `transitionend` 的逻辑仍会触发。JS 动画（`useCountUp`/`useFlash`）
在实现里自行判断，无需页面处理。

---

## 6. 新增页面的检查清单

- [ ] 首屏加载有骨架或 `v-loading`，**不要**先空后跳
- [ ] 空态用 `el-empty`（手机卡片列表用 `MobileCards` 自带空态）
- [ ] 关键数值用 `.metric-card` / `.value-num`，并考虑 `useCountUp`
- [ ] 列表入场用 `.anim-stagger`，单块用 `.anim-fade-in-up`（**不要**给表格行加）
- [ ] 可点击元素有 `.pressable` 或 `.hover-lift` 反馈
- [ ] 弹窗带 `append-to-body`
- [ ] 手机断点下表格降级为 `MobileCards`
- [ ] `vue-tsc --build` 与 `vite build` 均通过
