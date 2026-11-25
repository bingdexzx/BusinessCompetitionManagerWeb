# Debian 一键部署

目标：**Debian 12（或 Debian 系）全新服务器**，一条命令装好 PostgreSQL + 后端 + WebSocket + 前端 + Nginx + HTTPS + systemd。

## 1. 准备

- Debian 12+（root 或 sudo 权限），内存 ≥ 2GB；
- 域名已解析到服务器 IP（要 HTTPS 证书时必须）；
- 服务器能访问外网（apt / PyPI / npm / certbot）。

把仓库上传到服务器任意目录（或 `git clone`），然后：

```bash
cd BusinessCompetitionManagerWeb
sudo bash deploy/debian/install.sh
```

## 2. 交互流程（能生成的自动生成，不能猜的才问）

部署时会逐项询问，**直接回车 = 使用默认值**：

| 项 | 处理方式 | 默认 |
| --- | --- | --- |
| 站点域名 | **必须询问**（无法生成） | — |
| 安装目录 | 询问 | `/opt/bcm` |
| 管理员用户名 | 询问 | `admin` |
| 管理员邮箱 | 询问 | `admin@<域名>` |
| 管理员密码 | **自动生成**并展示一次（可选自己填） | 随机 12 位 |
| 数据库模式 | 询问 `local`（本机装）或 `existing`（用已有库） | `local` |
| 数据库名 / 用户 | 询问 | `business_competition_manager` / `bcm_app` |
| 数据库密码 | **自动生成**（existing 模式必须手填） | 随机 24 位 |
| worker 数 | 询问 | CPU 核数 |
| 每 worker 线程数 | 询问 | 8 |
| 申请 HTTPS | 确认 | 是 |
| 构建前端 | 确认（需要 Node 20，缺会自动装） | 是 |
| 启用 ufw | 确认（放行 SSH/80/443） | 是 |

`SECRET_KEY`（48 位随机）也在部署时**自动生成**写入 `.env`。

> 全自动（CI/无人值守）：
> ```bash
> sudo bash deploy/debian/install.sh --domain bcm.example.com --yes
> ```
> `--yes` 下所有默认值生效、密钥/密码自动生成；域名必须通过参数给。
> 已部署过、想复用已有数据库：
> ```bash
> sudo bash deploy/debian/install.sh --domain bcm.example.com --db-mode existing \
>   --db-host 10.0.0.5 --db-name bcm --db-user bcm --db-password '***' --yes
> ```


## 2.5 使用 1Panel 安装 PostgreSQL / Nginx（推荐）

如果你用 1Panel 管理服务器，**不需要让脚本再装一遍**：

1. 在 1Panel「应用商店」安装 **PostgreSQL** 和 **Nginx/OpenResty**；
2. 在 1Panel「数据库 → PostgreSQL」创建数据库与用户（记住密码）；
3. 在 1Panel「网站」创建一个站点（静态/PHP 均可），根目录填：
   `/opt/bcm/BusinessCompetitionManagerWebFrontend/dist`；
4. 运行部署脚本（只装 Python 依赖、构建前端、起 systemd 后端）：

```bash
sudo bash deploy/debian/install.sh \
  --domain bcm.example.com \
  --db-mode existing \
  --db-host 127.0.0.1 --db-port 5432 \
  --db-name bcm --db-user bcm --db-password '***' \
  --nginx-mode manual --yes
```

脚本会：

- **自动检测** 1Panel / Nginx / PostgreSQL 是否已存在，已存在就**跳过安装**；
- `--nginx-mode manual`：不修改系统 nginx，只把站点配置导出到
  `/opt/bcm/deploy/nginx/bcm.site.conf`，并打印 1Panel 里的两种配法
  （替换站点配置，或反向代理 `/api`→8000、`/ws`→8001 并开启 WebSocket）；
- 跳过 certbot（在 1Panel 网站设置里一键申请 SSL）与 ufw（1Panel 自带防火墙）。

> 不带 `--nginx-mode` 时：检测到 Nginx 会询问 `manage`（脚本写配置）还是
> `manual`（1Panel 里配）；检测到 1Panel 时默认 `manual`，防火墙默认交给 1Panel。

### 检测逻辑

| 组件 | 检测方式 | 已存在时 |
| --- | --- | --- |
| 1Panel | `/opt/1panel` 或 `1pctl` | 跳过 ufw；Nginx 默认 manual |
| Nginx | `nginx`/`openresty` 命令 | 不安装；按 `--nginx-mode` 处理 |
| PostgreSQL | 5432 端口监听 | 不安装；默认复用（existing） |
| certbot | `certbot` 命令 | 不重复安装 |

> 调试用：`--assume-detected nginx --assume-detected postgres --assume-detected onepanel`
> 可在没有对应组件的机器上预演「已安装」分支（配合 `--dry-run`）。

## 3. 它会做什么

1. `apt` 安装：python3、venv、nginx、rsync、postgresql（本地模式）、certbot；
2. 创建系统用户 `bcm` 与安装目录；
3. 同步项目代码（保留 `.env`、`media` 运行数据、日志）；
4. 生成 `/opt/bcm/.env`（含自动生成的 SECRET_KEY、数据库密码、生产安全配置）；
5. 用 `uv` 安装后端依赖（自动下载 Python 3.12，兼容 Debian 12 自带 3.11）；
6. 执行数据库迁移、创建管理员账号；
7. 构建前端（`npm ci && npm run build`）；
8. 写入并启动 `bcm.service`（waitress :8000 + daphne :8001，只监听 127.0.0.1）；
9. 写入 nginx 站点（静态 + `/api` + `/ws`，自动 SPA 回退、WebSocket 升级、上传大小）；
10. 可选 certbot 申请 HTTPS 并跳转；可选 ufw 防火墙；
11. 健康检查 + 汇总（含管理员密码与服务命令，保存在 `/opt/bcm/DEPLOY_SUMMARY.txt`，权限 600）。

## 4. 部署后

```bash
systemctl status bcm
systemctl restart bcm            # 改完 /opt/bcm/.env 后重启
journalctl -u bcm -f             # 后端日志
tail -f /var/log/nginx/access.log
```

- 访问 `https://<域名>`（未申请证书则 `http://<域名>`）；
- 管理员账号/密码在部署结束时打印，也在 `DEPLOY_SUMMARY.txt`；
- 数据库迁移、创建比赛等后续操作都在 Web 界面完成，新比赛会自动建独立库。

## 5. 预演（不修改系统）

任意系统都可先看计划：

```bash
python3 deploy/debian/deploy.py --dry-run --domain bcm.example.com --yes
```

## 6. 常见问题

| 现象 | 处理 |
| --- | --- |
| certbot 失败 | 域名未解析 / 80 端口被占；修复后手动 `certbot --nginx -d 域名` |
| 页面 404 | 前端未构建成功；`cd /opt/bcm/BusinessCompetitionManagerWebFrontend && npm run build` |
| 502 Bad Gateway | 后端没起来：`journalctl -u bcm -n 100 --no-pager` |
| WebSocket 连不上 | 检查 nginx `/ws/` 段是否保留 `Upgrade`/`Connection` 头 |
| 上传 413 | nginx `client_max_body_size` 小于 `.env` 的 `UPLOAD_MAX_BYTES` |
| 登录立刻失效 | HTTPS 未启用但 `SESSION_COOKIE_SECURE=true`：要么启用 HTTPS，要么改 `.env` 为 false 后重启 |
| 想换域名 | 改 `.env` 的 `ALLOWED_HOSTS`/`CORS_*`/`CSRF_*` + nginx `server_name`，重载两项服务 |
| 重复部署 | 直接再跑一次即可：代码会同步，`.env`/media/日志保留；数据库与管理员已存在会自动跳过 |

## 7. 文件

```
deploy/debian/
├── install.sh    # 入口（bash 包装，exec python3 deploy.py）
├── deploy.py     # 部署逻辑（交互/自动生成/幂等步骤）
└── README.md     # 本文件
```
