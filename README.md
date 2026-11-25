# Gipfel 商业竞争管理系统（重构版）

面向商赛（商业模拟比赛）的办赛平台：比赛管理、组队与公司、产业与财年、合同全流程、
股票市场、结算与获奖档案、区域总览、数据管理与工具箱。

技术栈：**Django 6（DRF + SimpleJWT + 多库路由）+ Vue 3（Vite + Pinia + Element Plus）+
PostgreSQL**。HTTP 走 waitress 多进程/多线程，WebSocket 走 daphne，跨进程推送用 PostgreSQL 通道层。

## 目录结构

```
BusinessCompetitionManagerWeb/            # 后端
  manage.py
  BusinessCompetitionManagerWeb/
    settings/base.py                      # 全局配置（全部由 .env 提供，含安全响应头/并发/缓存）
    settings/databases.py                 # 数据库拓扑 + 比赛库动态注册
    urls.py asgi.py wsgi.py
  apps/
    common/                               # 比赛上下文、脱敏、中间件、权限、缓存、广播
    global_/                              # 全局域（全局库）
      accounts/ useradmin/ schools/ competitions/ memberships/ teams/ invites/
      logs/ plugins/ packages/ profiles/ messages/
    competition/                          # 比赛域（每场一个 comp_<id> 库）
      routing.py provisioning.py
      companies/ industries/ contracts/ fiscal/ ledger/ fieldlogs/
      settlement/ messages/ audit/ stock/ regions/ basedata/ tools/ jobs
    plugins_runtime/                      # 插件运行时（AST 护栏 / 受控 ctx API / Effect）
BusinessCompetitionManagerWebFrontend/    # 前端（Vue 3 + Vite）
  src/views/  src/components/  src/api/  src/composables/
deploy/
  debian/                                 # Debian 一键部署（含 1Panel 场景）
  nginx/                                  # nginx 反向代理配置与说明
  pgbouncer/                              # PgBouncer（并发 >50 时可选）
tools/loadtest/                           # 独立压测工具（单文件 .bat）
scripts/                                  # 冒烟 / 压测 / 维护脚本
docs/                                     # 规范与设计文档（见文末索引）
```

## 快速开始（本地开发）

**1. 准备配置**

```powershell
Copy-Item .env.example .env     # 填 DATABASES_* 与 SECRET_KEY（生成命令见 .env.example 注释）
```

**2. 后端**

```powershell
uv sync                          # 安装依赖（项目要求 Python 3.12+）
.venv\Scripts\python.exe BusinessCompetitionManagerWeb\manage.py migrate
.venv\Scripts\python.exe scripts\run_servers.py --workers 4 --threads 8
```

- HTTP API：`http://127.0.0.1:8000`（waitress）
- WebSocket：`ws://127.0.0.1:8001`（daphne）
- 健康检查：`GET /api/health`

**3. 前端**

```powershell
cd BusinessCompetitionManagerWebFrontend
npm ci
npm run dev                      # http://localhost:5173（/api、/ws 已代理到 8000/8001）
```

生产构建：`npm run build`（产物 `dist/`，由 nginx 托管）。

**4. 首个超级管理员**

```powershell
$env:DJANGO_SUPERUSER_PASSWORD='你的密码'
.venv\Scripts\python.exe BusinessCompetitionManagerWeb\manage.py createsuperuser --username admin --email admin@example.com
```

## 配置

所有可调项集中在根目录 `.env`（完整说明见 [.env.example](.env.example)）：

- 数据库连接、`SECRET_KEY`、`DEBUG`、`ALLOWED_HOSTS`；
- CORS / CSRF / HTTPS / HSTS / 反向代理信任；
- worker 数与数据库并发预算、缓存 TTL、日志留存；
- 上传与比赛包体积、合同分页/同步上限、基础数据分页、计时器上限。

前端开发代理可用 `BusinessCompetitionManagerWebFrontend/.env` 的
`VITE_API_TARGET` / `VITE_WS_TARGET` 覆盖（见该目录 `.env.example`）。

## 数据库与多库架构

- **全局库**（`DATABASES_NAME`）：账号、学校、比赛元数据、身份、队伍、激活码、设备、网络日志、
  插件注册表、比赛包、个人档案；
- **每场比赛独立库 `comp_<id>`**：创建比赛/导入比赛包时自动建库并迁移全套比赛域表；
- 比赛域模型读写**必须**处于比赛上下文（URL `/api/competitions/{cid}/...` 或 `X-Competition-Id` 头），
  由 `CompetitionDatabaseRouter` 路由；跨库引用只存整数 ID。

> 网络日志已按月分区（`logs_networklog_pYYYYMM`），月度维护：
> `manage.py ensure_network_log_partitions --months 6`。

## 测试与压测

```powershell
# 后端全量测试
.venv\Scripts\python.exe BusinessCompetitionManagerWeb\manage.py test --noinput

# 前端类型检查 / lint / 构建
cd BusinessCompetitionManagerWebFrontend
npx vue-tsc --build ; npx eslint src ; npm run build
```

**独立压测工具**（单文件，可不依赖仓库运行）：双击 `tools/loadtest/loadtest.bat`，
输入网址 + 超管账号即可生成 Markdown/HTML 报告；说明见
[tools/loadtest/README.md](tools/loadtest/README.md)。

**容量基准**：`scripts/load_contract_mgmt.py`、`scripts/load_stock_sync.py`、
`scripts/load_throughput.py`（最近一次数据见 [docs/数据库优化.md](docs/数据库优化.md) §6）。

## 部署

**全新 Debian 服务器（脚本自动装齐）**

```bash
sudo bash deploy/debian/install.sh
# 默认自动安装并启动 PgBouncer（127.0.0.1:6432）；不需要可加 --no-pgbouncer
# 域名部署默认自动申请 Let's Encrypt 证书（--no-tls 可关闭）
# 没有域名、纯 IP 部署（不写 --ip 会自动检测本机 IP）：
# sudo bash deploy/debian/install.sh --ip 203.0.113.10 --yes
# 默认就是系统 nginx；想用 1Panel 配站点：--nginx-mode manual（80 被占用时 --stop-openresty）
```

**已用 1Panel 装好 PostgreSQL / Nginx**

```bash
sudo bash deploy/debian/install.sh \
  --domain bcm.example.com \
  --db-mode existing --db-host 127.0.0.1 --db-port 5432 \
  --db-name bcm --db-user bcm --db-password '***' \
  --nginx-mode manual --yes
```

脚本会检测已存在的组件并跳过安装，只导出 nginx 站点配置供 1Panel 使用。
详见 [deploy/debian/README.md](deploy/debian/README.md)；纯手工 nginx 见
[deploy/nginx/README.md](deploy/nginx/README.md)；高并发连接池见
[deploy/pgbouncer/README.md](deploy/pgbouncer/README.md)。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/更新报告-重构之后.md](docs/更新报告-重构之后.md) | 重构以来的更新总结（专业版，含升级须知） |
| [docs/API契约.md](docs/API契约.md) | 接口清单、鉴权、多库与错误约定 |
| [docs/比赛包格式规范.md](docs/比赛包格式规范.md) | 比赛包/插件格式、输入项、`ctx` 方法、Effect、公式与循环检测 |
| [docs/UI设计规范.md](docs/UI设计规范.md) | 版式、动效、按钮排布、提示分级、确认框、文案细则 |
| [docs/数据库优化.md](docs/数据库优化.md) | 连接层/索引/分区/缓存/容量实测/部署 |
| [docs/多核并发与吞吐优化.md](docs/多核并发与吞吐优化.md) | prefork 多进程模型、通道层、吞吐数据 |
| [docs/安全审计.md](docs/安全审计.md) | 安全基线、已修复问题、残余风险、部署侧清单 |
| [docs/实时同步覆盖.md](docs/实时同步覆盖.md) | 哪些资源会实时推送、怎么新增 |
| [docs/股票模块与同步优化.md](docs/股票模块与同步优化.md) | 股票快照+增量协议与防刷新风暴设计 |
| [tools/plugin-sdk/README.md](tools/plugin-sdk/README.md) | 插件开发 SDK：ctx 补全、常量构造函数、插件源码静态校验 |
| [tools/package-tools/README.md](tools/package-tools/README.md) | 比赛包工程：创建脚手架 / 校验 / 打包 |

## 常用命令

| 操作 | 命令 |
| --- | --- |
| 启动开发服务 | `scripts\run_servers.py --workers 4 --threads 8` |
| 后端测试 | `manage.py test --noinput` |
| 数据库迁移 | `manage.py migrate` |
| 新建比赛库 | 导入比赛包时自动建库；或 `manage.py provision_competition_db` |
| 网络日志留存 | `manage.py prune_network_logs --days 30 --keep 200000` |
| 广播流水留存 | `manage.py prune_broadcast_events --days 7 --keep 100000` |
| 慢请求报表 | `manage.py report_slow_requests --hours 24 --top 20` |
| 后台任务消费 | `manage.py run_jobs --watch`（结算/财年/导入） |

## 约定

- **权限**：页面/接口一律走 `apps/common/authority.py`（超级管理员 / 主席团 / 参赛选手），
  比赛级身份不再单独存在「比赛超级管理员」；
- **实时同步**：写接口成功后广播 `resource:changed`（推送只当信号，页面按资源重拉），
  断线按 `seq` 重放；见 [docs/实时同步覆盖.md](docs/实时同步覆盖.md)；
- **插件**：只允许导入可信比赛包；插件在进程内执行，导入前 AST 扫描，`ctx` 只读、改数据必须返回 `Effect`；
- **日志**：网络日志只增、按月分区、按策略留存；敏感字段统一脱敏。
