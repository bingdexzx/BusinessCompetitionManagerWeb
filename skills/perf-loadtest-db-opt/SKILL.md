---
name: perf-loadtest-db-opt
description: 压测驱动的性能诊断与数据库/后端/前端全链路优化方法论。当用户遇到"卡死/卡顿/很慢/超时/500/too many clients/连接数不够/同步数据量大/高并发"，或要求做压测、性能优化、数据库优化、连接池、慢查询、增量同步、防刷新风暴时使用。提供分层归因决策树（测量自检→WSGI/ASGI 对照→连接成本→SQL 热点→并发吞吐）、常见根因速查表、修复清单（连接复用/背压限流/keyset 分页/DISTINCT ON/快照+增量协议/推送当信号+去抖）、PostgreSQL 参数表与压测脚本模板。适用 Django/FastAPI 等任意 Python Web 栈与 PostgreSQL/MySQL。
license: MIT
metadata:
  version: "1.0"
  author: deepseek-harness-session
---

# 压测驱动的性能诊断与数据库优化（perf-loadtest-db-opt）

把「系统卡死」拆成**可实验证伪的分层归因**，每一层都有标准实验；修完后用**带思考时间的压测**验收。
核心纪律：**先证明瓶颈在哪一层，再动手优化**——本方法论的案例中，最大的假象（客户端 80ms/请求）
和最大的真凶（ASGI 单线程）都只有靠对照实验才能发现。

## 何时使用

- 系统"后期卡死/越来越慢"，尤其多账号并发、数据随时间滚雪球的场景
- 要做压测 / 容量评估 / 性能优化 / 数据库优化
- 出现 `too many clients`、连接超时、500 雪崩、请求堆积
- 全量同步/轮询数据量大导致前端卡顿

## 第 0 步：测量方法自检（防止误诊，先做！）

1. **压测客户端必须 TCP_NODELAY + 长连接**：Python urllib/http.client 默认受 Nagle/延迟 ACK
   影响，小包请求**每请求虚增 ~80ms**（实测 curl 4ms vs urllib 80ms）。
2. **对照工具交叉验证**：同一接口用 `curl -w "%{time_total}"` 与自写客户端各测一遍，
   差距 >10× 先修测量端。
3. **分阶段统计**：把「页面加载风暴」（初始全量）与「稳态增量」分开计，混在一起会把
   一次性成本误判成持续延迟。
4. **闭环 vs 真实节奏**：压测要加思考时间（如 1.5s/轮模拟前端去抖）；零思考闭环测出的
   延迟是排队放大，吞吐上限才是容量。

## 第 1 步：分层归因决策树（每层一个实验）

| 层 | 实验 | 命令/做法 | 结论指向 |
|----|------|----------|---------|
| 客户端 | curl vs 自写客户端 | `curl -o NUL -s -w "%{time_total}"` | 差距大 = 测量端假象（Nagle/短连接） |
| 服务管线 | 无 DB 逻辑端点（如 /health）压并发 | 并发探针（assets/probe_tools.py）| **WSGI 多线程 910 QPS vs ASGI 71 QPS** → Django 同步视图在 ASGI 下单线程敏感执行，HTTP 必须走 WSGI |
| 连接层 | 裸建连计时 + 复用查询计时 | probe_tools `connect-cost` | 新建连接 ~44ms vs 复用 0.03ms → 必须复用 |
| 连接数 | `SHOW max_connections` vs 2×并发线程 | — | 不够 → too many clients 雪崩 |
| 应用层 | 单请求逐接口计时（无并发） | probe_tools `request-breakdown` | 固定开销定位（中间件/建连/鉴权） |
| SQL 层 | 看慢查询日志 / EXPLAIN；警惕 N+1 变体 | `log_min_duration_statement=500ms` | 相关子查询、缺索引、OFFSET 分页 |
| 吞吐 | 并发递增找拐点（8→32→60） | load_test 模板 `--users` | 拐点=容量；延迟≈并发/吞吐 纯排队 |

**症状 → 根因速查表**：

| 症状 | 常见根因 | 修复 |
|------|---------|------|
| `FATAL: too many clients`、500 雪崩 | 连接数 < 2×并发线程；连接滞留 | max_connections ≥ 2×线程+余量；背压限流；PgBouncer |
| 单请求都慢（含 /health） | 每请求新建连接（~44ms/条） | CONN_MAX_AGE 复用 + 连接探活 |
| 并发一高延迟线性涨、吞吐封顶 | 单进程 GIL / ASGI 单线程 | HTTP 切 WSGI 多线程；再不够上多进程 |
| 后期越来越慢 | 全量同步滚雪球、N+1、无索引 | 快照+增量协议；DISTINCT ON；(updated_at,id) keyset 索引 |
| 推送一多就卡死 | 推送触发全量刷新风暴 | 推送只发信号 + 客户端去抖合并 + 单飞行去重 + 隐藏退避 |
| 前端列表卡 | 一次性渲染上千行 | 分页 50/页 / 虚拟滚动 / shallowRef / 乐观更新 |

## 第 2 步：修复清单（按收益排序）

1. **拓扑**：HTTP → WSGI 多线程（waitress/gunicorn）；WebSocket → ASGI（daphne/uvicorn）单独端口，
   nginx/vite 按 `/api`、`/ws` 分流。一键脚本模板见项目 `scripts/run_servers.py` 模式。
2. **连接层**：`CONN_MAX_AGE=60`（复用）+ `CONN_HEALTH_CHECKS=True` + `connect_timeout=5` +
   TCP keepalive；**前提** `max_connections ≥ 2×并发线程 + 后台`。
3. **背压限流**：中间件信号量封顶并发（≈max_connections/2 的一半），超时 503 + Retry-After——
   宁可排队/快速失败，不许雪崩假死。
4. **查询层**：(updated_at,id) 复合索引做 keyset 分页（不用 OFFSET）；批量取"每组最新一条"用
   `DISTINCT ON`（PostgreSQL）替代相关子查询；列表 `select_related/prefetch_related`；
   字段裁剪（列表薄字段，详情才带大 JSON）。
5. **同步协议**：首拉快照 + `since` 增量 + `serverTime` 服务端游标 + `hasMore` 续拉；
   **截断时游标降为已交付行 keyset 边界回拨 1µs**（防漏行，重复投递靠客户端按 id 幂等合并）。
6. **防风暴**：WS 推送只发 `{type, round}` 信号不带数据；客户端去抖 1.5s 合并一次增量、
   in-flight 去重、页面隐藏 10s 退避、失败回退快照。
7. **前端**：表格 50/页分页或虚拟滚动、shallowRef、下单/操作乐观更新+增量校正不拉全量。

## PostgreSQL 参数表（按内存调，改后重启）

| 参数 | 建议起点 | 说明 |
|------|---------|------|
| `max_connections` | ≥ 2×并发线程+余量（多库架构×2 个库） | 太小直接 too many clients |
| `shared_buffers` | 内存 25% | 常用数据缓存 |
| `effective_cache_size` | 内存 50–75% | 优化器估计值 |
| `work_mem` | 16–64MB | **×连接数放大，勿激进** |
| `maintenance_work_mem` | 512MB–1GB | 建索引/导入提速 |
| `max_wal_size` | 2–8GB | 写多场景少 checkpoint |
| `autovacuum_vacuum_scale_factor` | 0.05–0.1 | 大表默认 20% 才清理太迟 |
| `log_min_duration_statement` | 500ms | 慢查询定位 N+1/缺索引 |

调连接数（需重启服务）：`ALTER SYSTEM SET max_connections = 200;` + 重启 PG 服务。
并发再上去：PgBouncer(transaction pooling) → 多进程 → 读写分离 → Redis 缓存（每步都有判断标准，别提前上）。

## 第 3 步：压测与验收

- **脚本**：assets/load_test_template.py（通用模板，改 ENDPOINTS 即可）；
  项目版 `scripts/load_stock_sync.py` 是完整范例（预热+稳态分阶段、60 账号、思考时间）。
- **规模**：账号数=真实活动人数；数据量=后期峰值（股票 800×30 轮 K 线 ≈ 2.4 万行量级）。
- **指标**：每接口 P50/P95/P99 + 错误数 + QPS；目标示例：热路径 P50<100ms、P95<400ms（真实节奏）、
  0 错误；容量余量 ≥ 2×真实负载。
- **验收模板**：预热（页面加载风暴）单列一栏；稳态计时窗单列一栏；错误必须为 0。

## 案例实测（本方法论出处，2026-10）

60 账号 × 800 股票 × 30 轮 K 线（2.4 万行）+ 持仓/委托，修复后稳态：
增量同步 P50=58ms、行情分页 P50=73ms、持仓 P50=40ms，0 错误；真实节奏负载 47 QPS vs 容量 95 QPS。
完整过程与数字见 references/case-study.md。

**案例 2（合同域）**：2000+ 合同 × 50 管理员，列表 P50 6,991ms → **34ms（≈205×）**——
头号根因是**列表 N+1**（每合同每方查一次公司）+ JSON 可见性 Python 过滤 + 无分页；
修复 = 批量公司映射 + `parties__contains`(JSONB)+GIN 索引下推 + 服务端分页/字段裁剪。
详见 references/case-study-contracts.md（含"列表 SQL 条数体检"等教训）。
