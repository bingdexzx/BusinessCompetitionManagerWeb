# Debian 部署 / 运维脚本（v2）

一个脚本覆盖：**安装、升级、体检、状态查看**。能自动判断的都自动判断，只问需要人决定的；
重复执行安全，失败时给出下一步。

```bash
# 交互式安装（推荐第一次用）
sudo bash deploy/debian/install.sh

# 全自动（自动探测本机 IP、自动生成密钥/密码/管理员密码）
sudo bash deploy/debian/install.sh install --yes

# 纯 IP
sudo bash deploy/debian/install.sh --ip 203.0.113.10 --yes

# 已部署环境升级：同步代码 → 依赖 → 迁移 → 构建前端 → 重启
sudo bash deploy/debian/install.sh upgrade

# 只体检，不改系统
python3 deploy/debian/deploy.py doctor

# 看服务/健康/数据库/访问地址
python3 deploy/debian/deploy.py status
```

## 它比旧版聪明在哪

| 场景 | 自动处理 |
| --- | --- |
| 地址没给 | `--yes` 时自动探测本机 IP（并提示公网不同请用 `--ip`） |
| 已是 Debian + root | 自动跳过前置检查；非 Debian/非 root 直接拒绝并说明 |
| 已装依赖 | `dpkg -s` 逐个判断，只 apt 安装缺的 |
| 已有 `.env` | 复用数据库连接与 `SECRET_KEY`，部署/升级不会改密、不会让登录态失效 |
| 本机已有 PostgreSQL | 默认复用；自动创建数据库（用输入的用户/密码，owner 为该用户） |
| 1Panel / OpenResty / 旧服务占着 80 | **优先停旧服务保留 80**：nginx 只更新配置并 reload；OpenResty/其他旧服务会尝试停掉；拒绝或无法识别则报错，不会自动占用 8080 |
| uv 的 Python 在 /root 下 | 固定装到 `/opt/uv-python`，并检测到旧 venv 指向 `/root` 时自动重建 |
| 前端站点目录受限（1Panel） | `--site-dir` 自动 `rsync` dist 进去并 `chown www:www` |
| 机器没有 Node.js | 询问后装 Node 20；`--no-frontend-build` 可跳过 |
| 数据库不存在 | 自动建库；无权限时提示去 1Panel 建库或 `ALTER ROLE ... CREATEDB` |
| PgBouncer | **默认自动安装并启动**（127.0.0.1:6432，transaction pooling），应用自动改连 6432 |
| 数据库连不上 | 迁移前单独校验，报错直接给出当前 `用户@主机:端口/库` 与修复命令 |
| 管理员不存在 | 自动创建并**校验确实存在**；`--reset-admin-password` 可重置已有账号 |
| 证书申请失败 | 自动回退 HTTP（关闭 Cookie Secure/HSTS）并给出原因；修好 DNS/80 后重跑即可 |
| 重复执行 | 安装/升级都是幂等的：已存在则跳过，`.env`/media/日志保留 |

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--ip <IP>` / `--domain <域名>` | 访问地址（二选一；IP 自动按纯 IP 模式处理） |
| `--app-dir` | 安装目录，默认 `/opt/bcm` |
| `--site-dir` | 把前端 dist 同步到该目录（1Panel 站点根目录） |
| `--db-mode local\|existing` | 本机装 PostgreSQL / 使用已有库 |
| `--db-name/--db-user/--db-password/--db-host/--db-port` | 数据库连接 |
| `--nginx-mode system\|manage\|manual` | **默认 system（系统 nginx）**；manage=写现有 nginx；manual=只导出配置（1Panel） |
| `--http-port` | nginx 端口，默认 80；被占用会停旧服务保留 80，无法处理则报错，不会自动换端口 |
| `--stop-openresty` | 80 被 1Panel OpenResty 占用时停掉它 |
| pgadmin4 保护 | 检测到 80/指定端口被 pgadmin4 占用时直接报错，不会停它 |
| `--tls` / `--no-tls` | 是否申请 Let's Encrypt 证书（**域名默认自动申请**；`--no-tls` 关闭） |
| `--force-cert` | 域名解析与本机 IP 不一致时仍尝试申请 |
| `--workers/--threads` | 覆盖自动推导的 waitress 进程数/线程数 |
| `--db-tune` / `--no-db-tune` | 是否按硬件自动写 PostgreSQL 内存/连接参数（默认开启） |
| `--admin-user/--admin-email/--admin-password` | 管理员账号 |
| `--reset-admin-password` | 已存在时重置密码为本次密码 |
| `--no-frontend-build` | 使用现有 dist，不构建 |
| `--pgbouncer` / `--no-pgbouncer` | 是否安装并启动 PgBouncer（默认开启） |
| `--firewall` / `--no-firewall` | 是否启用 ufw |
| `--yes` | 全部默认值/自动生成，不逐项询问 |
| `--dry-run` | 只打印计划，不执行 |
| `--verbose` | 打印每条命令 |

## 硬件自动调参

脚本会读取本机 **CPU 核数 / 内存 / 磁盘**，自动推导：

| 参数 | 规则（示例） |
| --- | --- |
| `workers × threads` | `min(CPU, 8) × 8`；总线程上限 96；内存不足 1.5GB 时线程降为 4 |
| `DB_MAX_CONCURRENT_REQUESTS` | 等于总线程数 |
| PostgreSQL `max_connections` | `总线程 × 2 + 20`，限制在 50–500 |
| `shared_buffers` | 内存的 25%，限制 128MB–8GB |
| `effective_cache_size` | 内存的 60%，限制 256MB–16GB |
| `work_mem` | 按内存和并发推导，4–32MB |
| `maintenance_work_mem` | 内存的 5%，64MB–1GB |
| PgBouncer `max_client_conn` | 应用线程 × 2 + 50，100–2000 |
| PgBouncer `default_pool_size` | 应用线程 ÷ 2，10–100 |

示例：

```
2 核 / 2GB   → 2 worker × 8 线程，max_connections 52，shared_buffers 512MB
4 核 / 8GB   → 4 worker × 8 线程，max_connections 84，shared_buffers 2GB
8 核 / 16GB  → 8 worker × 8 线程，max_connections 148，shared_buffers 4GB
```

应用方式：

- **新装的本地 PostgreSQL**：写入 `ALTER SYSTEM` 并重启 PostgreSQL 生效；
- **本机已有 PostgreSQL**：跳过自动内存参数，避免影响同机其他库；
- **已有外部库（1Panel/Docker/远程）**：不改数据库参数，只调整应用线程与 PgBouncer；
- 想完全关闭：加 `--no-db-tune`。

`upgrade` 会按 `.env` 里的 `WEB_CONCURRENCY` 重新计算 PgBouncer 参数，不会改 PostgreSQL
内存参数（避免升级时重启数据库）；需要重调 PostgreSQL 请重新执行 install 或手工
`ALTER SYSTEM`。

## 安装流程

1. 环境探测（Debian/root/1Panel/OpenResty/nginx/PostgreSQL/Node/磁盘/内存/CPU/IP）；
2. 只安装缺失的系统包；
3. 数据库：复用或创建库/用户；**安装并启动 PgBouncer（127.0.0.1:6432）**；
4. 创建 `bcm` 系统用户与安装目录；
5. `rsync` 同步代码（保留 `.env`、media、日志）；
6. 生成 `.env`（自动生成 `SECRET_KEY` / 数据库密码 / 管理员密码）；
7. `uv` 安装 Python 3.12 与依赖（固定 `/opt/uv-python`）；
8. 建库/校验连接 → 迁移 → 确保管理员存在；
9. 构建前端（可选同步到 `--site-dir`）：
   - `npm ci` → `vue-tsc` → `vite build` **串行**执行，避免小内存机器并行 OOM；
   - 自动设置 `NODE_OPTIONS=--max-old-space-size=<内存×60%>`；
   - 每步有 600–900s 超时，卡住会失败退出而不是无限等待；
10. 写 systemd 服务并启动（waitress :8000 + daphne :8001，仅监听 127.0.0.1）；
11. 写 nginx 站点（SPA 回退、`/api`、`/ws`、上传上限、安全头）；
12. **自动申请 HTTPS 证书**（域名模式默认开启：certbot + 自动续期 timer，失败回退 HTTP）
    与可选 ufw；
13. 健康检查，输出摘要到 `/opt/bcm/DEPLOY_SUMMARY.txt`（600）。

## 升级流程

`upgrade` 假定 `.env` 已存在且可用：

```
同步代码 → 依赖 → 校验数据库 → 迁移 → 构建前端（+ site-dir 同步）→ 重启服务 → 健康检查
```

不会重新生成密码/密钥，也不会覆盖 `.env`。

## 体检（doctor）

检查项：Debian/root/磁盘、`.env` 关键键、`bcm` 服务与 `/api/health`、8000/8001 监听、
nginx 站点配置。退出码 `1` 表示有问题。

## 状态（status）

输出安装目录、服务状态、健康检查、数据库连接、访问地址、站点目录与常用命令。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 80 被占用 | 脚本会识别并停掉旧 nginx/OpenResty/服务；pgadmin4 不会被停；无法识别时手工停掉占用进程后重跑，或用 `--http-port` 显式选空闲端口 |
| 1Panel 站点目录受限 | 用 `--site-dir /opt/1panel/.../sites/<站点>/index` |
| 数据库不存在 | 脚本会自动建；失败时去 1Panel 建库，或给用户 `CREATEDB` |
| 登录/接口 502 | `systemctl status bcm` + `journalctl -u bcm -n 100` |
| 前端 404 | 确认 `dist/index.html` 存在；重新 `upgrade` |
| 证书失败 | 确认域名解析与 80 端口；稍后 `certbot --nginx -d 域名` |
| PgBouncer 起不来 | `journalctl -u pgbouncer -n 50`；确认 `/etc/pgbouncer/userlist.txt` 权限 600；不需要可加 `--no-pgbouncer` |

> 本脚本只在 Debian 上执行真实系统操作；`--dry-run` / `doctor` / `status` 可在其它系统预览。
