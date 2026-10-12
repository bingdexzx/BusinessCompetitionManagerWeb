# 案例实测：60 账号「后期卡死」的完整归因与修复（本 skill 出处）

场景：商赛系统比赛后期（60+ 账号），股票行情 + 合同全量同步数据量大（800 股票 × 30 轮
K 线 ≈ 2.4 万行 + 持仓/委托），轮询与推送触发的刷新叠加 → 界面卡死。
技术栈：Django + DRF + PostgreSQL 多库（全局库 + 每比赛独立库）+ Vue。

## 归因过程（按 skill 决策树逐层）

| 步骤 | 实验 | 结果 | 结论 |
|------|------|------|------|
| 测量自检 | curl vs Python urllib 同接口 | 4ms vs 80ms | 客户端 Nagle/延迟 ACK 假象，修 TCP_NODELAY+长连接 |
| 连接层 | 裸建连计时 vs 复用查询 | 44ms vs 0.03ms | 必须连接复用；`CONN_MAX_AGE=60` |
| 连接数 | 60 并发压测 | `FATAL: too many clients` 500 雪崩 | 连接随线程滞留打满 max_connections=100；调 200 + 背压限流（并发 32） |
| 服务管线 | /api/health 32 并发：daphne vs waitress | **71.7 vs 909.7 QPS** | Django 同步视图在 ASGI 下单线程敏感执行 → **HTTP 切 WSGI**，ASGI 只跑 WS |
| SQL | sync 接口 profile | 涨跌幅批量取末根 K 线走相关子查询（500 股≈500 子计划 200ms+） | 改 `DISTINCT ON` 单次索引扫描（~5ms） |
| 协议 | 截断续拉核对 | `serverTime=响应时刻` 会漏未交付尾部行 | 游标改「已交付边界回拨 1µs」+ 客户端幂等合并 |
| 吞吐 | 闭环 0 思考 vs 1.5s 思考 | 95 QPS 上限；真实节奏 47 QPS | 单进程 GIL 天花板；真实负载余量 2×，更大活动上多进程 |

## 修复清单（全部落地）

1. 快照+增量同步协议（`?since=<serverTime>`、keyset 分页、hasMore 续拉、字段裁剪）；
2. HTTP/WS 分端口拓扑（waitress 32 线程 :8000 + daphne :8001，一键 `run_servers.py`）；
3. `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS` + keepalive + connect_timeout；
4. `DatabaseBackpressureMiddleware` 背压限流（信号量 32，超时 503 + Retry-After）；
5. `max_connections` 100→200（`ALTER SYSTEM SET` + 重启服务）；
6. `DISTINCT ON` 消 N+1 变体；(updated_at,id) 索引；
7. WS 推送只发信号 + 前端去抖 1.5s/in-flight 去重/隐藏退避/50 行分页/乐观更新。

## 验收数字（60 并发、稳态计时窗 20s、0 错误）

| 接口 | P50 | P95 |
|------|-----|-----|
| 增量同步（热路径） | 58ms | 341ms |
| 行情分页 | 73ms | 172ms |
| 持仓/资金 | 40ms | 88ms |

- 页面加载风暴（60 人同时拉初始快照）：P50 4.6s —— 一次性、时间分散，前端 limit=2000+续拉缓解；
- 真实节奏负载 47 QPS vs 单进程容量 95 QPS（余量 2×）；
- 修复前后对照：500 雪崩+秒级卡死 → 0 错误+百毫秒级。

## 教训

1. **先修测量再优化**：urllib 的 80ms/请求假象差点把方向带偏（怀疑过 SQL、怀疑过 GIL）；
2. **对照实验出真凶**：WSGI/ASGI 各压一遍才暴露单线程敏感执行（13 倍差距）；
3. **多库架构的连接预算是 2×**：每请求同时占全局库+比赛库两条连接；
4. **分阶段统计**：页面加载风暴与稳态混合统计会把一次性成本误判成持续延迟。
