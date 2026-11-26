# API 契约（重构版）

> 所有接口挂 `/api` 前缀；REST + JWT（`Authorization: Bearer <access>`）。
> 比赛域接口统一为 `/api/competitions/{cid}/...`，由多库路由解析到对应比赛库。
> 请求头约定：`X-Competition-Id`（缺省时按 URL 解析）、`X-Trace-Id`、`X-Device-Screen`。
> 错误响应统一：`{ code, message, details }`；成功响应均为 camelCase JSON。
>
> **维护约定（2026-11 起）**：接口以代码为准，本文随改动同步；最近一次核对：2026-11-25。

## 2026-11 接口变更

| 变更 | 说明 |
| --- | --- |
| **移除** `GET /competitions/{cid}/contracts/export` | 合同 xlsx 导出功能已删除（连同前端按钮/API） |
| 合同列表分页 | `?page&pageSize&status&q`，默认 50/页、上限 200（可用 `.env` 的 `CONTRACT_PAGE_SIZE*` 调整） |
| 合同增量同步 | `?updatedAfter=<ISO>&limit=`，默认 500、上限 1000 |
| 后台任务 | `GET/POST /competitions/{cid}/jobs`、`GET /competitions/{cid}/jobs/{id}`（结算、财年、导入） |
| 工具箱计时器 | `GET/POST /competitions/{cid}/timers`、`PATCH/DELETE /competitions/{cid}/timers/{id}`（按用户隔离） |
| 基础数据下拉 | `GET /competitions/{cid}/basedata/{table}?nodeType=城市点位` 等，支持按节点类型过滤 |
| WebSocket | `ws://.../ws/notifications?token=<access>`；token 只用于握手，不写入访问日志 |

## 1. 账号 / 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册 `{username, password, email, displayName, schoolId?}`——`displayName` 为**真实姓名，必填**（≤100，全站展示用） |
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
| GET/POST | `/competitions/{cid}/teams` | 队伍列表（含 `companyId`/`companyName`，未分配为空串）/ 队长建队 `{name, industryChoice[], industryAdjustAccepted[]}`；**必须先进入本比赛**（见下） |
| GET | `/competitions/{cid}/teams/{tid}` | 队伍详情（成员、产业志愿） |
| POST | `/competitions/{cid}/teams/{tid}/join-codes` | 生成组队码 `{maxUses?}`（队长） |
| POST | `/competitions/{cid}/teams/join` | 凭组队码加入 `{code}`；同样**必须先进入本比赛** |
| PATCH | `/competitions/{cid}/teams/{tid}/industry` | **管理员手动调整** `{industryFinal, industryChoice?, industryAdjustAccepted?}`；同步创建/更新公司并回填产业初始值 |
| POST | `/competitions/{cid}/teams/{tid}/company` | **分配/修改队伍公司** `{industryKey, companyName}`（系统超管 / 比赛超管）→ 建/改公司（一队一公司）并按产业回填初始字段值；分配后**队长可操作**本公司、**队员只读** |
| GET | `/competitions/{cid}/industries` | 本比赛**已导入**的产业插件 `[{key, name, version}]`（分配公司选产业用；比赛成员可见） |
| GET | `/competitions/{cid}/industry-fields` | 本比赛全部产业字段元数据 `[{id, key, name, fieldType, dataTable, pluginKey}]`（前端把 `cash` 这类字段键显示成中文名；比赛成员可见） |
| GET/POST | `/competitions/{cid}/invites` | 激活码列表 / 生成 `{identity?, maxUses?, validDays?, note?}`（超管） |
| POST | `/invites/redeem` | 凭激活码加入比赛 `{code}` → 获得比赛内身份 |

> **公司权限口径（2026-10 决策）**：`user_company_ids`（可查看：队长 + 队员）与
> `user_operable_company_ids`（可操作：**仅队长**，另含所辖管理员/超管）分离——
> 队员可只读查看本公司合同/行情/公司表格，下单、建单、确认、申请修改等**操作仅队长**。
> **兼任**：管理员（主席团）同时当队长/队员时，本队公司与所辖公司**取并集**（查看并集；
> 操作＝所辖公司 ∪ 本人任队长的队伍公司），避免"既当裁判又参赛"的人看不到自己公司。
>
> **组队准入（2026-10）**：**队伍归属比赛**——没进入比赛就不能建队/进队。建队与
> 凭组队码进队都要求调用者已有**有效**成员身份（激活码兑换或管理员添加），否则 403：
> 未加入 →「请先加入本比赛（激活码 / 管理员添加）后再组队」；身份被停用 →
> 「你的参赛身份已被停用，请联系比赛管理员」。**不会**因为组队而自动补成员身份。

## 4. 比赛包 / 合同类型 / 插件（M1）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/competitions/{cid}/package` | 上传比赛包（multipart `file`）→ 导入报告。**无比赛状态限制**：报名中/进行中也可重导入；合同实例按指纹幂等去重（报告 `contractsSkipped`，见《比赛包格式规范》§7.1） |
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
| GET | `/competitions/{cid}/contracts/{id}` | 详情 **含 timeline**（§14.6 确认时间线：谁/何时/设备/IP）与 **checks**（§7.3 四检查点落库：`roundStatus: ACTIVE/HISTORY`，修改后按轮次回放当时的检查内容）。两者按 `audit_company_ids` 下发：**参赛代表不下发**；主席团只下发所辖公司相关的字段节点/依据；系统超管与比赛超管全量 |
| POST | `.../contracts/{id}/submit` | T2 提交（运行 check，保证创建即能执行） |
| POST | `.../contracts/{id}/confirm` | T3 逐方确认；末方确认后**自动编号 + 自动执行 + 落账**（T4/T5） |
| GET | `.../contracts/{id}/effects` | 不可变落账审计（before/after/roundNo + `roundStatus: ACTIVE/ROLLED_BACK`）+ **重演值** `replayBefore/replayAfter`（按当前内容重算，上游修改后自动同步；与当时值不一致=上游被改过）。可见范围同 timeline：选手 ❌、主席团仅所辖公司、超管全量 |
| GET | `.../contracts/{id}/ledger` | **资金账本链（查账）**：该合同触及的 (公司,字段) 全链 `{initialValue → nodes[当时值+重演值+检查依据重演] → currentValue}`，按编号顺序重放生效效果。可见范围同 timeline：选手 ❌、主席团仅所辖公司、超管全量 |
| POST | `.../contracts/{id}/request-modify` | T6 申请修改 `{reason}`（任意参与方） |
| POST | `.../contracts/{id}/modify/review` | T7/T7' 超管审核 `{action: approve\|reject, note?}` |
| POST | `.../contracts/{id}/modify/other-party` | T8/T8' 其他方表态 `{action: approve\|reject, note?}` |
| POST | `.../contracts/{id}/modify/submit` | T9/T10 修改定稿 `{inputs?, parties?}` → 回滚旧落账 → 重检查 → 自动执行 → 重落账 |
| POST | `.../contracts/{id}/backfill/review` | 补录合同超管审核 `{action: approve\|reject, note?}` |

## 6. 公司 / 产业字段（§6.3 实体信息表 / 财务报表）

### 6.1 基础数据管理（数据管理页；基础数据不再随比赛包导入）

统一通用契约（字段照旧项目口径，camelCase=旧字段名）：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/competitions/{cid}/basedata/{table}?page&pageSize&q` | 列表 `{items, total, page, pageSize}`，`q` 过滤名称（map_edges 按起终点名/ID） |
| POST | `/api/competitions/{cid}/basedata/{table}` | 新增（超管）→ 行；body 可带 `relations` 嵌套数组 |
| GET | `/api/competitions/{cid}/basedata/{table}/{id}` | 行（含 `relations`） |
| PATCH | `.../basedata/{table}/{id}` | 编辑（超管）→ 行；body 可带 `relations` 整体替换 |
| DELETE | `.../basedata/{table}/{id}` | 删除（超管）→ `{ok:true}` |
| GET | `.../basedata/{table}/{id}/impact` | 删除影响 `{removable, refs:[{kind,label,count}]}` |

`table` ∈ `fuels / warehouses / vehicles / materials / products / parts / infrastructures /
tech_nodes / production_lines / map_node_types / path_types / map_nodes / map_edges`。

- 行字段 camelCase 照旧模型字段名（`pricePerLiter`、`fuelConsumptionPerKm`、
  `maxMaterialCargo`/`maxPartCargo`/`maxProductCargo`、`carbonEmissionCoefficient`、
  `nodePrices`（JSON 字符串）、`activationPrice`、`laborCount`、`maxPerYear`、
  `employmentRateBonus`…），通用列 `id/name/createdAt/updatedAt`；金额 Decimal(60,4)。
- **关联内嵌**：行/列表项带 `relations` 对象（`products → {parts:[{id,partId,partName,ratio}],
  techRequirements:[{id,techNodeId,techNodeName}]}`；`parts → {materials:[{id,materialId,
  materialName,ratio}], techRequirements:[...]}`；`tech_nodes → {prerequisites:[{id,
  prerequisiteId,prerequisiteName}]}`；`vehicles → {pathTypes:[{id,pathTypeId,pathTypeName}]}`；
  `map_nodes → {edgesCount}`）。POST/PATCH body 接受同名 `relations` 嵌套数组（平铺同名数组
  为兼容别名）**整体替换**：带 `id` 更新、无 `id` 新增、缺失删除（upsert by id）。
- **impact**：删除影响检查（旧语义）。`refs` 统计引用/级联行数；`removable=false` 表示存在
  **外部引用**（删除会破坏其他主数据，如 fuel 被 vehicles 引用、part 被 products 引用、
  map_node 被 map_edges 引用）→ 前端提示并拒绝删除；自身级联子配置计入 `refs`（展示
  「将级联删除」）但不阻塞。
- 权限：查看=本比赛成员；写入=系统超管或本比赛超管；错误响应 `{code,message,details}`（中文）。

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

## 8. 结算 / 获奖 / 奖牌（M5，§11；2026-10 需求变更）

> **权限口径（需求方确认）：结算与获奖（配置/结果/榜单/发放）仅超管可见**（系统超管 / 比赛超管）。
> 参赛代表与管理员的**获奖记录与电子奖牌在个人档案**（`/me/awards`、`/me/medals`）查看。
>
> **结算只算分**：产出各公司得分与名次，**不再按名次自动评奖**。
> **奖项人工设定 + 人工发放**：超管先建「奖项定义」（个人奖 / 集体奖，奖牌等级可选），
> 再对**具体人**（个人奖）或**具体公司**（集体奖 = 该公司对应队伍全员）发放；
> 发放结果写入个人档案，可撤销。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/competitions/{cid}/settlement/config` | 评分准则 + 奖项定义；GET 返回 `{criteria, awards}`；POST `{kind:'criterion', name, fieldKey, aggregation, direction, weight}` 或 `{kind:'award', name, awardKind:'INDIVIDUAL'\|'COLLECTIVE', description?, medalLevel?}` |
| DELETE | `.../settlement/config/{criterion\|award}/{id}` | 删除准则 / 奖项定义（删奖项定义会**连带撤销**其已发放记录，返回 `revokedRecords`） |
| POST | `.../settlement/run` | 开始结算（超管）→ 只算得分与名次 |
| GET | `.../settlement/result` | 最近结算结果（`entries: companyId/companyName/rank/score/detail`） |
| GET | `.../settlement/candidates?q=` | 个人奖候选人（本比赛全部成员，含所属公司） |
| GET | `.../awards` | 本比赛结算名次（companyId/companyName/rank/score） |
| GET | `.../awards/grants` | 已发放奖项记录（奖项/类型/发放对象/受益人数/备注/发放人/时间） |
| POST | `.../awards/grants` | 发放：个人奖 `{awardId, userId, note?}`；集体奖 `{awardId, companyId, note?}` → `{id, recipientCount, recipients[]}` |
| DELETE | `.../awards/grants/{id}` | 撤销发放（回收个人档案对应记录）→ `{ok, removed}` |
| GET | `/me/awards` | 个人档案：获奖记录（`awardName/awardKind/awardKindLabel/competitionName/teamName/medalId/medalName/createdAt`） |
| GET | `/me/medals`、`/me/medals/{id}` | 电子奖牌（**仅在线展示**，D12） |
| POST | `/medals` | 奖牌资产管理（系统超管） |

## 9. 站内信 / 日志 / 审计（M6，§14）

**站内信（系统级，独立于比赛）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/messages` | 收件箱（站内信/公告/系统通知统一收件箱；`?unread=1&kind=&limit&offset`，返回 total/unread/items） |
| GET | `/messages/sent` | 我发送的（含收件人阅读状态） |
| POST | `/messages/send` | **已关闭发送**（2026-11）：管理员与参赛选手均返回 403；仅保留历史查看 |
| POST | `/messages/{recipientId}/read` | 标记已读（按收件人记录） |
| POST | `/messages/read-all` | 全部已读 |
| GET | `/messages/address-book` | 收件人多选框数据：比赛（选中=全员）+ 个人 |

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/logs/network` | 网络日志（仅系统超管；`?userId&competitionId&deviceId&traceId&status&method&path&from&to&limit&offset`，返回 `total/items`；总数缓存 10s） |
| POST | `/logs/network/export` | 导出网络日志（仅系统超管） |
| GET | `/logs/devices` | 设备管理（仅系统超管） |
| GET | `/competitions/{cid}/logs/fields` | 字段日志（**仅系统超管 / 比赛超管**；`?companyId&fieldKey&contractId&operatorId&source&event&traceId&from&to`） |
| POST | `.../logs/fields/export` | 导出字段日志（同上，仅超管） |
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
| 查看字段日志 | ✅ | ✅（本比赛） | ❌ | ❌ |
| 合同审计（确认时间线/检查记录/效果与账本/资金账本链） | ✅ | ✅ | ✅（**仅所辖公司**） | ❌ |
| 审计日志 | ✅ | ✅（本比赛） | ❌ | ❌ |
| 查看网络日志/设备/导出 | ✅ | ❌ | ❌ | ❌ |

## 11. 2026-10 缺口补齐新增接口（旧功能对齐）

> 依据《缺口补齐任务计划》（决策：区域/需求补齐、账号安全补齐、合同删除保留、平台四件套）。

**账号与安全**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/auth/change-password` | 改密（`{oldPassword,newPassword}`），成功后顶号（tokenVersion+1） | 登录用户 |
| GET/POST | `/api/users` | 账号列表（?page&pageSize&q）/ 新建 | 系统超管 |
| GET/PATCH/DELETE | `/api/users/{id}` | 详情 / 修改 / 删除（禁删自己与最后一个超管） | 系统超管 |
| POST | `/api/users/{id}/password` | 重置密码（顶号） | 系统超管 |
| GET | `/api/version` | 版本下发（前端轮询比对，不一致硬封锁） | 公开 |
| — | 登录限流 | 同 用户名\|IP 5 分钟失败 10 次锁 15 分钟（可配），429 + Retry-After | — |

**区域 / 消费者需求（比赛域，comp_<id> 库）**

> **区域总览 = 旧系统口径（2026-10 需求：与旧版一致）**：区域**在地图管理里创建**
> （地图节点的 `region` 字段），区域总览页**不提供**区域新建/重命名/删除。
> - 区域列表 = `MapNode.region`（去重，按节点创建顺序）∪ 已有 Region 实体；
> - 区域内公司 = 公司「**所在地**」（`field_key=location`）字段值 == 该区域下某个地图节点名；
>   该字段由产业插件字段迁移时自动补建（照旧系统的 `_ensure_location_field`），值需人工填写；
> - 区域名保存卡片时若无 Region 行会自动补建（以便挂卡片配置）。

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| **GET** | `/api/competitions/{cid}/regions/map-overview` | **区域总览数据源**：`[{id, region, companies:[{id,name,industryKey}], cards:[{id,displayName,companyId,industryFieldId,zone,value,valid,fieldType}]}]`（卡片由服务端算好当前值；`valid=false` 表示公司/字段已失效） | 读=成员 |
| **PUT** | `/api/competitions/{cid}/regions/by-name/{区域名}/overview-cards` | **按区域名**保存卡片 `{cards:[{id,displayName,companyId,industryFieldId,zone}]}` → `{success:true}`（无 Region 行则补建；区域名需 URL 编码） | 写=比赛超管 |
| GET | `/api/competitions/{cid}/companies/{pk}/industry-fields` | 该公司可选的产业字段 `[{id,key,name,fieldType}]`（数据框「产业字段」下拉） | 可查看该公司 |
| GET/POST | `/api/competitions/{cid}/regions` | 区域列表（含 demandCount）/ 新建（名称唯一） | 读=成员；写=比赛超管 |
| GET/PATCH/DELETE | `/api/competitions/{cid}/regions/{id}` | 区域详情 / 改名 / 删除 | 同上 |
| GET/PUT/PATCH | `/api/competitions/{cid}/regions/{id}/overview-cards` | 按区域 id 整表替换卡片（与 by-name 等价，保留兼容） | 同上 |
| GET/POST | `/api/competitions/{cid}/consumer-demands` | 需求列表（?regionId，含 `regionName`）/ 新建（**`region` 区域名** 或 `regionId`、productId、quantity、note） | 同上 |
| GET/PATCH/DELETE | `/api/competitions/{cid}/consumer-demands/{id}` | 需求详情 / 修改 / 删除（变更触发所在区域公司字段重算，公式可用 `consumerDemand` 特殊键） | 同上 |

**合同删除**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| DELETE | `/api/competitions/{cid}/contracts/{id}?rollback=1\|0` | 删除（回滚）=按轮次回滚落账+解冻后删；不回滚删除=仅限无落账效果合同；写 CONTRACT_DELETE 审计 | 比赛超管/系统超管 |

**系统管理**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET/PUT | `/api/system/rate-limit` | 流量限制配置查询/保存（登录限流三参数 + API 每分钟五角色限额 + 开关；PUT 整体校验） | 系统超管 |
| POST | `/api/system/rate-limit/reset` | 恢复默认配置 | 系统超管 |
| DELETE | `/api/system/rate-limit/records` | 清空限流记录（RequestThrottle + LoginThrottle） | 系统超管 |
| POST | `/api/files/upload` | 通用文件上传（≤100MB，扩展名白名单） | 登录用户 |
| GET | `/api/files/view/<path>` | 读取已上传文件（拒绝路径穿越） | 登录用户 |
| GET/POST/PATCH/DELETE | `/api/competitions/{cid}/files/map-background` | 地图背景服务端持久化（multipart 文件或 url + transform） | 读=成员；写=比赛超管 |
| POST | `/api/messages/upload-image` | 消息图片（≤5MB，≤9 张） | 登录用户 |

**仪表盘 / 实时广播**
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET | `/api/competitions/{cid}/dashboard` | 仪表盘布局（比赛包 `dashboard.json`，组件绑定产业字段值） | 本比赛成员 |
| WS | `/ws/notifications`（新增帧） | `subscribe/unsubscribe/replay` 请求；`resource:changed/replay/subscribed/denied` 事件（写接口成功即广播，seq 单调可重放） | 登录用户（订阅须本比赛成员） |
