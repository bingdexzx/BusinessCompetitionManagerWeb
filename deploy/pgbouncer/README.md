# PgBouncer（transaction pooling）—— 400 人规模接入

> 本项目 HTTP 走 waitress 多进程/多线程、WS 走 daphne；每个线程会持有「全局库 + 当前比赛库」
> 两条连接。并发线程数上去后，PostgreSQL 的 `max_connections` 会先被吃满。
> PgBouncer 用事务级池化把 **客户端连接数** 和 **服务端连接数** 解耦。

## 1. 架构

```
Django (many threads)  ──►  PgBouncer :6432  ──►  PostgreSQL :5432
        max_client_conn=600        default_pool_size=30
```

- 全局库与动态比赛库（`comp_<id>`）都用同一条 `* =` 通配规则，不需要为每场比赛加配置；
- `pool_mode = transaction`；Django 的 `CONN_MAX_AGE` 可继续用（长连接在 bouncer 侧被复用）。

## 2. 部署（Docker 示例）

```bash
cd deploy/pgbouncer
cp userlist.txt.example userlist.txt   # 用 pg_authid 的 SCRAM 哈希替换占位
DB_PASSWORD=*** docker compose up -d
docker compose logs -f pgbouncer
```

没有 Docker 的机器：`apt install pgbouncer`（或编译）后把 `pgbouncer.ini` 放到
`/etc/pgbouncer/`，`systemctl enable --now pgbouncer`。

## 3. 应用侧切换

```powershell
$env:DATABASES_HOST = '127.0.0.1'
$env:DATABASES_PORT = '6432'          # 指向 PgBouncer
$env:DATABASES_CONN_MAX_AGE = '60'
# transaction pooling 下禁用服务端游标（psycopg2 named cursor 跨事务会失效）
$env:DATABASES_DISABLE_SERVER_SIDE_CURSORS = 'true'
```

> `settings/base.py` 里已读取 `DATABASES_HOST/PORT/CONN_MAX_AGE`；服务端游标开关若尚未读取
> 环境变量，需要在 `DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS']` 显式设置。

比赛库配置会克隆全局库配置（`competition_db_config`），所以只改全局库即可全部生效。

## 4. 参数建议

| 参数 | 建议 | 说明 |
| --- | --- | --- |
| `max_client_conn` | 600 | ≈ 在线用户峰值（400 人 + 冗余） |
| `default_pool_size` | 25–30 | 每库服务端连接；PG `max_connections` 可降到 100 |
| `pool_mode` | `transaction` | session 模式会占住连接，不要用 |
| `query_wait_timeout` | 15s | 池满时快速失败，避免请求无限排队 |
| PG `max_connections` | 100（有 bouncer 后） | 8 worker × 8 线程 = 64 客户端连接，池化后服务端只需 30–50 |

## 5. 验证

```powershell
.venv\Scripts\python.exe scripts\load_throughput.py --users 64 --duration 10
.venv\Scripts\python.exe scripts\load_contract_mgmt.py --users 32 --seconds 20 --think 0.2
```

关注：错误数为 0、P95 不劣化；同时 `psql -c "show max_connections"` 与
`select count(*) from pg_stat_activity` 看服务端连接数是否稳定在池大小附近。

## 6. 注意事项

1. 事务级池化下**不能用** `SET`/`SET SESSION`、会话级 advisory lock、跨事务临时表；
   本项目合同落账用 `select_for_update`（事务内），兼容；
2. Django 的 `CONN_HEALTH_CHECKS` 保留即可；
3. 若后续引入 `LISTEN/NOTIFY` 长连接（本项目用 PG channel 表轮询，不走 notify），
   需要单独的 session 池或直连；
4. 回滚：把 `DATABASES_PORT` 改回 `5432` 即可，无数据变更。
