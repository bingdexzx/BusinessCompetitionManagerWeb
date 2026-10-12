# API 契约（重构版）

> 所有接口挂 `/api` 前缀；REST + JWT（`Authorization: Bearer <access>`）。
> 比赛域接口统一为 `/api/competitions/{cid}/...`，由多库路由解析到对应比赛库。
> 请求头约定：`X-Competition-Id`（缺省时按 URL 解析）、`X-Trace-Id`、`X-Device-Screen`。
> 错误响应统一：`{ code, message, details }`；成功响应均为 camelCase JSON。

## 1. 账号 / 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册 `{username, password, email, displayName?, schoolId?}` |
| POST | `/auth/login` | 登录 `{username, password}` → `{access, refresh, user}` |
| POST | `/auth/refresh` | 刷新 `{refresh}` → `{access}` |
| GET | `/me` | 个人信息（含 memberships：各比赛身份） |
| PATCH | `/me` | 更新 `{displayName?, email?, schoolId?}` |
| GET | `/me/devices` | 本人登录设备列表 |

## 2. 学校 / 比赛 / 成员

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/schools` | 学校列表（GET 公开，`?q=`）/ 创建（超管） |
| GET/POST | `/competitions` | 比赛列表 / 创建 `{name, code?, coverImage?, hostSchoolId?, location?, staffingInfo?}`（超管） |
| GET | `/competitions/{cid}` | 比赛详情（含 code、status） |
| PATCH | `/competitions/{cid}/meta` | 完善比赛信息（超管/比赛超管） |
| POST | `/competitions/{cid}/transition` | 生命周期 `{target}`：PACKAGE_IMPORTED→ENROLLING→RUNNING→SETTLING→CLOSED |
| GET/POST | `/competitions/{cid}/members` | 成员列表 / 指派 `{username, identity, managedCompanies?}`（系统超管；identity ∈ COMP_SUPER_ADMIN/ADMIN/PLAYER） |
| PATCH | `/competitions/{cid}/members/{mid}` | 调整 `{identity?, managedCompanies?, isActive?}` |

## 3. 组队 / 激活码（M2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/competitions/{cid}/teams` | 队伍列表 / 队长建队 `{name, industryChoice[], industryAdjustAccepted[]}` |
| GET | `/competitions/{cid}/teams/{tid}` | 队伍详情（成员、产业志愿） |
| POST | `/competitions/{cid}/teams/{tid}/join-codes` | 生成组队码 `{maxUses?}`（队长） |
| POST | `/competitions/{cid}/teams/join` | 凭组队码加入 `{code}` |
| PATCH | `/competitions/{cid}/teams/{tid}/industry` | **管理员手动调整** `{industryFinal, industryChoice?, industryAdjustAccepted?}`；同步创建/更新公司并回填产业初始值 |
| GET/POST | `/competitions/{cid}/invites` | 激活码列表 / 生成 `{identity?, maxUses?, validDays?, note?}`（超管） |
| POST | `/invites/redeem` | 凭激活码加入比赛 `{code}` → 获得比赛内身份 |

## 4. 比赛包 / 合同类型 / 插件（M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/competitions/{cid}/package` | 上传比赛包（multipart `file`）→ 导入报告 |
| GET | `/competitions/{cid}/packages` | 导入历史（含报告） |
| GET | `/competitions/{cid}/contract-types` | 合同类型 schema（partyRoles / inputSchema / numberPrefix） |
| GET | `/plugins` | 插件注册表（系统超管，`?kind=CONTRACT\|INDUSTRY`） |

## 5. 合同（M3/M4，状态机见《重构方案》§3）

状态：`BACKFILL_REVIEW → DRAFT → PENDING_PARTY → PENDING_EXEC → EXECUTED → POSTED`；
修改环 `POSTED → MOD_APPLYING → MOD_EDITING → PENDING_EXEC(回滚重执行) → POSTED`；`EXEC_FAILED / CANCELLED`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/competitions/{cid}/contracts` | 合同列表（**服务端分页 + 薄字段**）：`?page&pageSize&status&q` → `{items, total, page, pageSize}`；**增量同步**：`?updatedAfter=<ISO>` → `{items, serverTime, hasMore, mode:'delta'}`（游标用上次 `serverTime`）。可见性：系统/比赛超管全量，其余按可操作公司过滤（JSONB containment + GIN 索引） |
| POST | `/competitions/{cid}/contracts` | 创建草稿 `{contractTypeKey, pluginVersion?, name?, parties[{role, companyId}], inputs{}, isBackfill?, fiscalYearId?}` |
| GET | `/competitions/{cid}/contracts/{id}` | 详情 **含 timeline**（§14.6 确认时间线：谁/何时/设备/IP）与 **checks**（§7.3 四检查点落库：`roundStatus: ACTIVE/HISTORY`，修改后按轮次回放当时的检查内容） |
| POST | `.../contracts/{id}/submit` | T2 提交（运行 check，保证创建即能执行） |
| POST | `.../contracts/{id}/confirm` | T3 逐方确认；末方确认后**自动编号 + 自动执行 + 落账**（T4/T5） |
| GET | `.../contracts/{id}/effects` | 不可变落账审计（before/after/roundNo + `roundStatus: ACTIVE/ROLLED_BACK`）+ **重演值** `replayBefore/replayAfter`（按当前内容重算，上游修改后自动同步；与当时值不一致=上游被改过） |
| GET | `.../contracts/{id}/ledger` | **资金账本链（查账）**：该合同触及的 (公司,字段) 全链 `{initialValue → nodes[当时值+重演值+检查依据重演] → currentValue}`，按编号顺序重放生效效果 |
| POST | `.../contracts/{id}/request-modify` | T6 申请修改 `{reason}`（任意参与方） |
| POST | `.../contracts/{id}/modify/review` | T7/T7' 超管审核 `{action: approve\|reject, note?}` |
| POST | `.../contracts/{id}/modify/other-party` | T8/T8' 其他方表态 `{action: approve\|reject, note?}` |
| POST | `.../contracts/{id}/modify/submit` | T9/T10 修改定稿 `{inputs?, parties?}` → 回滚旧落账 → 重检查 → 自动执行 → 重落账 |
| POST | `.../contracts/{id}/backfill/review` | 补录合同超管审核 `{action: approve\|reject, note?}` |

## 6. 公司 / 产业字段（§6.3 实体信息表 / 财务报表）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/competitions/{cid}/companies` | 公司列表（按可见性过滤） |
| GET | `.../companies/{id}/tables/{entity\|finance}` | 实体信息表 / 财务报表（值按财年展开） |
| PATCH | `.../companies/{id}/fields` | 手工修改 `{fieldKey, value, fiscalYearId?}`（冻结字段拒绝，source=MANUAL） |

## 7. 财年 / 补录（M4，§10.2）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/competitions/{cid}/fiscal-years` | 财年列表（含备份数） |
| POST | `.../fiscal-years/open` | 开启财年（FY_START 定时器；超管） |
| POST | `.../fiscal-years/close` | 结束财年（自动备份各公司字段数据表 + FY_END 定时器；超管） |
| GET | `.../fiscal-years/{id}/backups` | 备份快照（实体信息表+财务报表） |

补录合同：创建时 `isBackfill: true, fiscalYearId` → `BACKFILL_REVIEW` → 超管审核 → 正常确认链 →
以**所补录财年末快照**为执行基准落账，**非财年定时器字段自动同步**（字段日志 source=BACKFILL_SYNC）。

## 8. 结算 / 获奖 / 奖牌（M5，§11）

> **权限口径（需求方确认）：结算与获奖（配置/结果/榜单）仅超管可见**（系统超管 / 比赛超管）。
> 参赛代表与管理员的**获奖记录与电子奖牌在个人档案**（`/me/awards`、`/me/medals`）查看。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/competitions/{cid}/settlement/config` | 评分准则/获奖规则；POST `{kind: criterion\|award, ...}` |
| DELETE | `.../settlement/config/{kind}/{id}` | 删除准则/规则 |
| POST | `.../settlement/run` | 开始结算（超管）→ 评分、名次、获奖 |
| GET | `.../settlement/result` | 最近结算结果（entries: companyId/rank/score/awardLevel/detail） |
| GET | `.../awards` | 本比赛获奖信息 |
| GET | `/me/awards` | 个人档案：历史参赛与获奖记录（含 medalId） |
| GET | `/me/medals`、`/me/medals/{id}` | 电子奖牌（**仅在线展示**，D12） |
| POST | `/medals` | 奖牌资产管理（系统超管） |

## 9. 站内信 / 日志 / 审计（M6，§14）

**站内信（系统级，独立于比赛）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/messages` | 收件箱（站内信/公告/系统通知统一收件箱；`?unread=1&kind=&limit&offset`，返回 total/unread/items） |
| GET | `/messages/sent` | 我发送的（含收件人阅读状态） |
| POST | `/messages/send` | 发送 `{title, body, recipientUserIds[], competitionIds[]}`——**个人自由**；**按比赛批量（公告）仅超管**；自动去重 |
| POST | `/messages/{recipientId}/read` | 标记已读（按收件人记录） |
| POST | `/messages/read-all` | 全部已读 |
| GET | `/messages/address-book` | 收件人多选框数据：比赛（选中=全员）+ 个人 |

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/logs/network` | 网络日志（仅系统超管；`?userId&competitionId&deviceId&traceId&status&method&path&from&to&limit&offset`） |
| POST | `/logs/network/export` | 导出网络日志（仅系统超管） |
| GET | `/logs/devices` | 设备管理（仅系统超管） |
| GET | `/competitions/{cid}/logs/fields` | 字段日志（按可见公司过滤；`?companyId&fieldKey&contractId&operatorId&source&event&traceId&from&to`） |
| POST | `.../logs/fields/export` | 导出字段日志 |
| GET | `/competitions/{cid}/audit-logs` | 比赛内审计（超管） |

## 10. 权限矩阵（§15.2 摘要）

| 动作 | 系统超管 | 比赛超管 | 管理员(主席团) | 参赛代表 |
|------|:---:|:---:|:---:|:---:|
| 创建比赛/导入比赛包 | ✅ | ✅（本比赛） | ❌ | ❌ |
| 开关财年 / 调整队伍产业 | ✅ | ✅ | ❌ | ❌ |
| 成员管理（身份指派/所辖公司） | ✅ | ❌ | ❌ | ❌ |
| 创建/确认本方合同 | ✅ | ✅ | ✅（所辖公司） | ✅（本队公司） |
| 审核修改申请 / 审核补录 | ✅ | ✅ | ❌ | ❌ |
| 结算配置/运行/结果/获奖 | ✅ | ✅ | ❌ | ❌ |
| 个人档案获奖/电子奖牌 | ✅ | ✅ | ✅ | ✅（本人） |
| 查看字段日志 | ✅ | ✅（本比赛） | ✅（所辖公司） | ✅（本队公司） |
| 审计日志 | ✅ | ✅（本比赛） | ❌ | ❌ |
| 查看网络日志/设备/导出 | ✅ | ❌ | ❌ | ❌ |
