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


---

## 10. 按钮 / 提示 / 确认 / 文案（2026-11 统一）

### 10.1 按钮排布

| 位置 | 约定 |
| --- | --- |
| 页面级操作 | 统一放 `PageHeader` 的 `#actions`（右上）；**整页只保留一个 `type="primary"`**，且放最右 |
| 列表工具条 | `搜索框 → 筛选 → 分隔线 → 次要按钮（同步/导出）→ 主按钮（新建）`，顺序固定 |
| 表格行内操作 | `link` + `size="small"`，顺序 `详情 → 编辑 → 危险操作`；危险操作用 `type="danger"` |
| 动态行（清单/需求/数据框等） | 用「移除」；实体记录（公司/合同/账号）用「删除」 |
| 弹窗底部 | 右侧：`取消`（默认按钮）+ 动作按钮（`primary` 或 `danger`） |
| 文案 | 动词开头，不带 `+`、`→`、`←` 等符号；需要图标用 `:icon` 传入 |

### 10.2 提示分级

| 场景 | 用法 | 示例 |
| --- | --- | --- |
| 动作完成 | `ElMessage.success`，短句、**不带句号** | `已保存` / `合同已删除` / `已导出` |
| 校验 / 前置条件 | `ElMessage.warning` | `请选择合同类型` / `至少填写一项采购清单` / `「原料清单」有未选择原料的行` |
| 请求失败 | `ElMessage.error(errorMessage(err, 'XX失败'))` | `加载失败` / `保存失败` / `导出失败` |
| 中性说明 | `ElMessage.info` 或 `el-alert type="info"` | `需先导入比赛包后方可推进` |

失败原因一律经过 `errorMessage(err, '…')`，不要直接展示后端英文报错。

### 10.3 确认框

1. 标题 = **动作（或动作 + 对象）**：`删除奖项`、`开始结算`、`撤销发放`；正文里必须出现对象名称；
2. 正文 = **影响说明**：会发生什么、是否可恢复（`删除后不可恢复`、`对应档案记录会一并删除`）；
3. `confirmButtonText` = 动作词（`删除` / `移除` / `发放` / `撤销` / `开始结算`），`cancelButtonText` 固定 `取消`；
4. 危险操作统一 `type: 'warning'`；
5. 不再依赖 Element 默认的「确定」。

### 10.4 文案规范

- 中文全角标点；省略号统一 `…`（技术 URL 里的 `...` 除外）；
- 数字、金额、日期分别走 `formatNumber` / `formatDateTime`，不手写格式；
- 同一动作只用一个词：

| 场景 | 统一用词 | 不要用 |
| --- | --- | --- |
| 创建 | 新建（页面级）、创建（弹窗确认） | `+ 新建`、`新增`、`添加` |
| 修改 | 编辑（入口）、保存（提交） | `修改`（作为按钮） |
| 删除实体 | 删除 | `移除` |
| 移除列表行 | 移除 | `删除` |
| 重新取数 | 刷新（按钮）、重试（失败后） | `刷新数据`、`重新加载`、`刷新页面` |
| 返回 | 返回列表 / 返回 | `← 返回合同列表` |
| 导出 | 导出 Excel / 导出 | `下载` |

术语表：比赛、比赛包、合同、参赛者、公司、队伍、财年、结算、奖项、纪念券、工具箱、数据管理。

---

## 11. 文案细则（角色 / 句式 / 标点）

> 原《界面文案规范》已并入本节；原则：**同一类信息只允许一种句式**；短句不加句末标点；
> 参数与前缀用中文冒号。

### 1. 角色称呼

| 统一写法 | 不再使用 |
|---|---|
| 超级管理员 | 系统超级管理员、超管、系统超管 |
| 主席团 | 管理员（指主席团时仍写「主席团」） |
| 参赛选手 / 队长 / 队员 | 选手、玩家 |

> 比赛级「超级管理员」身份已取消，权限并入系统超级管理员；界面一律写「超级管理员」。

### 2. 成功提示

格式：**`<对象>已<动作>`**（不加句号）。

- ✅ 学校已删除、比赛信息已保存、账号已创建、字段值已更新
- ❌ 已删除、保存成功、删除成功

**例外（认证/自身动作类事件）**：登录成功、注册成功、密码已修改，请重新登录、已加入比赛「X」、已加入队伍「X」、已推进至「X」。

### 3. 失败 / 警告 / 权限提示

- 有原因：**`<动作>失败：<原因>`**，如「复制失败：请手动复制」「比赛包导入失败：请查看导入报告」
- 无原因：**`操作失败，请稍后重试`**
- 权限：
  - 页面级：**`仅超级管理员可<动作>`**（或「仅超级管理员可见」）
  - 操作级：**`无权<动作>`**，如「无权查看该比赛」「无权操作地图背景」
- 禁止使用「需要管理员权限」「需要系统超级管理员权限」这类裸权限句。

### 4. 表单校验

| 控件 | 句式 | 示例 |
|---|---|---|
| 单行文本 / 数字 | `请输入XX` | 请输入名称、请输入价格 |
| 下拉 / 日期 / 单选 | `请选择XX` | 请选择办赛学校、请选择开始时间 |
| 多行文本 | `请填写XX` | 请填写修改原因 |
| 后端必填兜底 | `XX必填` | 比赛名称必填、字段值必填 |

长度/格式统一写法：

- `XX长度需为 8-128 位`
- `XX最长 100 个字符`
- `XX格式不正确`（如「邮箱格式不正确」）

### 5. 确认框（ElMessageBox）

- 标题：**`<动作><对象>`**，如「删除账号」「结束财年」
- 正文：**`确定<动作><对象>？<后果说明>。`**
  - 问句用「？」，后果句用「。」；**不使用「吗」**
- 不用「确认删除…」，统一用「确定删除…」

示例：`确定删除学校「第一中学」？该学校下的账号会保留，仅清空学校归属。`

### 6. 标点与符号

- 短提示（toast / 校验 / 空态 / 按钮 / 标签 / placeholder）：**不加句末标点**
- 长句（确认框、页面说明）：问句「？」，陈述句「。」
- 引号统一「」，英文双引号仅出现在代码中
- 冒号统一中文「：」（如「已选择起点：A」）
- 省略号统一「…」
- 中英文/数字之间保留半角空格：`8-128 位`、`SHA-256`、`K 线`

### 7. 空态

- 无数据：**`暂无<对象>`**，如「暂无合同」「暂无财年」
- 搜索无结果：**`没有匹配的记录`**
- 受限页面：`仅超级管理员可查看XX` / `仅超级管理员可见`

### 8. Placeholder

- 输入框：`请输入XX`；选择器：`请选择XX`
- 筛选器沿用简洁名词（如「全部」「按状态筛选」），不强制加动词
- 动态 placeholder 使用 `f.placeholder || '请输入' + label` 时保持统一前缀
