# Gipfel 商业竞争管理系统（重构版）

按 [`重构方案.md`](重构方案.md) 全流程推倒重写（决策 D7：历史数据不迁移）。技术栈：
**Django（DRF + JWT + 多库路由）+ Vue 3 + Element Plus**。

> 当前进度：**M0–M6 全部完成**（骨架 / 比赛包与插件 / 账号与组队 / 合同核心 /
> 修改与补录 / 结算与档案 / 消息日志收尾），端到端冒烟 43/43 通过。
> API 契约见 [`docs/API契约.md`](docs/API契约.md)；《比赛包格式规范》v0.1 见
> [`docs/比赛包格式规范.md`](docs/比赛包格式规范.md)（§10 有 5 项待需求方确认）。

## 目录结构（对齐重构方案 §5.3）

```
BusinessCompetitionManagerWeb/            # 后端（Django + DRF + SimpleJWT）
  manage.py
  BusinessCompetitionManagerWeb/
    settings/                             # settings 按 global/competition 拆分
      base.py                             #   全局域/公共配置
      databases.py                        #   数据库拓扑 + 比赛库动态注册（PostgreSQL）
    urls.py  asgi.py  wsgi.py
  apps/
    common/                               # 上下文(traceId/比赛/设备)、脱敏、中间件、权限、主体解析
    global_/                              # 全局域（存全局库）
      accounts/                           #   用户、JWT、一账号多身份
      schools/                            #   学校
      competitions/                       #   比赛元数据 + 生命周期 + 比赛代码（编号 D13）
      memberships/                        #   比赛内身份（超管/主席团/参赛代表）
      teams/                              #   队伍、组队码、产业志愿与调剂（M2）
      invites/                            #   激活码（加入比赛获得身份，M2）
      logs/                               #   设备实体 + 网络日志（只增不删）
      plugins/ packages/                  #   插件注册表 / 比赛包导入编排（M1）
      profiles/                           #   个人档案、获奖记录、电子奖牌（M5）
    competition/                          # 比赛域（存 comp_<id> 比赛库）
      routing.py                          #   多库路由器
      provisioning.py                     #   建库即迁移（CREATE DATABASE + migrate）
      companies/                          #   公司 + 实体信息表/财务报表（M3）
      industries/                         #   产业字段定义、公式求值与级联重算
      contracts/                          #   合同状态机引擎（engine.py）、确认链、编号、
      |                                   #   落账效果审计、修改流程（M3/M4）
      fiscal/                             #   财年、自动备份、补录基准（M4）
      ledger/                             #   落账冻结（字段级，决策 D10）
      fieldlogs/                          #   字段日志（值变更+结构变更，只增不删，§14.2）
      settlement/                         #   评分准则/获奖规则/结算（M5）
      messages/ audit/                    #   比赛内消息与审计
  plugins_runtime/                        # Python 插件运行时（AST 护栏/版本化/受控 API）
BusinessCompetitionManagerWebFrontend/    # 前端（Vue 3 + Vite + Pinia + Element Plus）
scripts/                                  # 冒烟/清理脚本
  smoke_full.py                           #   M2–M6 端到端冒烟（43 项）
  smoke_m0.py / smoke_m1.py               #   M0 / M1 冒烟
  make_sample_package.py                  #   生成示例比赛包
docs/                                     # API 契约 / 比赛包格式规范
backup/                                   # 脚手架时期旧数据备份（D7 不迁移，仅留存）
```

## 多库架构（决策 D1 / §5.2）

- **全局库**（`.env` 的 `DATABASES_NAME`）：账号、学校、比赛元数据、比赛内身份、队伍/激活码、
  设备、网络日志、插件注册表、比赛包、获奖档案；
- **每场比赛独立库 `comp_<id>`**（PostgreSQL）：创建比赛/导入比赛包时自动 `CREATE DATABASE`
  + `migrate` 全套比赛域表；
- `CompetitionDatabaseRouter` 按线程局部比赛上下文路由：比赛域模型的读写**必须**处于比赛上下文
  （请求 `/api/competitions/{cid}/...` 或携带 `X-Competition-Id` 头）；
- 跨库引用（用户等）一律存整数 ID，不建外键。

## 快速开始

```powershell
# 1. 配置 .env（参考 .env.example；DATABASES_* 为 PostgreSQL 连接）
# 2. 后端（HTTP=waitress 多线程 :8000 + WebSocket=daphne :8001，一键启动）
uv sync
.venv\Scripts\python.exe BusinessCompetitionManagerWeb\manage.py migrate
.venv\Scripts\python.exe BusinessCompetitionManagerWeb\manage.py bootstrap_superadmin <用户名> --password <密码>
.venv\Scripts\python.exe scripts\run_servers.py

# 3. 前端（另开终端）
cd BusinessCompetitionManagerWebFrontend
npm install
npm run dev        # http://localhost:5173，/api→8000、/ws→8001
```

> **为什么不用 runserver？** 压测实测 Django 同步视图在 ASGI(daphne) 下单线程敏感执行，
> 32 并发仅 ~72 QPS；WSGI 多线程(waitress) 同场景 ~910 QPS。故 HTTP 与 WebSocket
> 分端口部署（详见 [docs/数据库优化.md](docs/数据库优化.md) §1.0）。

## 验证

```powershell
# 单元测试（脱敏/设备解析/多库路由/AST 护栏/表格解析/引擎纯函数）
.venv\Scripts\python.exe BusinessCompetitionManagerWeb\manage.py test apps

# M0 / M1 冒烟
.venv\Scripts\python.exe scripts\smoke_m0.py
.venv\Scripts\python.exe scripts\smoke_m1.py

# M2–M6 端到端冒烟（43 项：组队/激活码 → 合同状态机 → 修改回滚重落账 →
# 财年备份/补录 → 结算/奖牌 → 消息/权限；脚本可重复运行，自动清理残留）
.venv\Scripts\python.exe scripts\smoke_full.py

# 生成示例比赛包（《比赛包格式规范》配套）
.venv\Scripts\python.exe scripts\make_sample_package.py
```

## 交付清单（M0–M6）

| 里程碑 | 能力 | 状态 |
|--------|------|------|
| M0 | 多库路由 + 建库即迁移、JWT、一账号多身份、设备登记、网络日志（脱敏）、比赛生命周期、成员指派 | ✅ |
| M1 | 比赛包解析/校验/回滚、Python 插件加载器（AST 护栏/版本/审计）、表格导入、产业字段迁移、导入报告、《比赛包格式规范》初稿 | ✅ |
| M2 | 学校、注册/激活码加入比赛、组队码组队、产业志愿与调剂、管理员手动调整产业（→公司建档+初始值）、管理员所辖公司指派 | ✅ |
| M3 | 合同插件执行（check/apply）、N 方确认链、统一编号（`PO-<比赛代码>-FY1-0001`）、确认后自动执行、再次检查落账、字段级冻结、不可变效果审计、字段日志、确认时间线（谁/何时/设备/IP） | ✅ |
| M4 | 修改申请→超管审核→其他方逐一通过→回滚旧落账→重检查→自动执行→重落账（roundNo+1）；财年开关、FY 定时器、自动备份；补录合同（超管审核、财年末快照基准、非定时器字段自动同步） | ✅ |
| M5 | 可配置评分引擎（指标/聚合/方向/权重）、并列同名次跳号、获奖规则、结算结果、获奖同步个人档案、电子奖牌（仅在线展示） | ✅ |
| M6 | 消息中心（合同确认/修改/补录提醒、跨比赛汇总）、**WebSocket 实时推送（/ws/notifications）**、比赛内审计、字段日志检索/导出、网络日志中心/设备管理前端、权限矩阵落地 | ✅ |

## 实现口径说明（按文档语义的工程解释）

1. **冻结（§7.4，决策 D10）**：字段级冻结拦截**非合同写入路径**（手工修改字段等）；
   合同自身的落账管线（已审计、事务、检查）继续可写，落账合同的修改必须走修改流程（解冻→重落账→再冻结）。
2. **补录同步（§2.2 阶段五）**：补录以所补录财年末快照为检查/效果基准，效果改写该财年数据行；
   非财年定时器字段的变化同步到「当前数据」行并记 `BACKFILL_SYNC` 字段日志。
3. **公式求值**：产业字段 formula 支持四则运算（字段名作变量），AST 白名单求值（不用 `eval`）。
4. **实时通信**：`/ws/notifications`（Django Channels + JWT 鉴权）实时推送合同确认/修改审核/
   补录审核/结算等通知，前端弹窗 + 顶栏未读铃；开发用内存通道层，生产多进程请切 Redis
   （见 `settings/base.py` CHANNEL_LAYERS 注释）。WebSocket 连接/断开同样入网络日志（§14.3）。

## 待需求方确认（跟进项，§18）

| # | 事项 | 状态 |
|---|------|------|
| 1 | **评分准则**细则/表格（指标、权重、并列处理） | ⏳ 框架已就绪（ScoringCriterion/AwardRule），收到细则后配置 |
| 2 | **《比赛包格式规范》** | ✅ v1.0 已确认（§10 五项取舍定稿） |
| 3 | **合同类别前缀清单**（统一编号前缀映射） | ⏳ 暂用插件 `NUMBER_PREFIX`（示例 PO/LN），随合同类型清单固化 |
