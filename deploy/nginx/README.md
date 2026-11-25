# Nginx 反向代理（生产入口）

> 拓扑：nginx（:80/:443）→ 前端 `dist/` 静态文件 + `/api`（waitress :8000）+ `/ws`（daphne :8001）。
> 开发环境不需要它（Vite 已有代理）；这是给「单机直连部署」用的。

## 1. 准备

```powershell
# 1) 构建前端（产物是静态文件，由 nginx 直接托管）
cd BusinessCompetitionManagerWebFrontend
npm run build          # 生成 dist/

# 2) 启动后端两个服务（只监听本机，公网只开 nginx）
cd ..
$env:WEB_CONCURRENCY='4'
$env:DB_MAX_CONCURRENT_REQUESTS='64'
.venv\Scripts\python.exe scripts\run_servers.py --workers 4 --threads 8 --no-reload
```

后端建议只绑定 `127.0.0.1`（`run_servers.py --host 127.0.0.1`，默认即本机），
公网不要暴露 8000/8001，只暴露 nginx 的 80/443。

## 2. 安装与部署

### Linux

```bash
sudo apt install nginx
sudo cp deploy/nginx/nginx.conf /etc/nginx/nginx.conf          # 或只合并 http 段
sudo cp deploy/nginx/bcm.conf   /etc/nginx/conf.d/bcm.conf
# 把 bcm.conf 里的 server_name / root 路径改成你的
sudo nginx -t && sudo systemctl reload nginx
```

### Windows

1. 下载 <https://nginx.org/en/download.html> 解压到 `C:\nginx`；
2. 用 `deploy/nginx/nginx.conf` 覆盖 `C:\nginx\conf\nginx.conf`（把 `user` 行删掉，
   日志/pid 路径改成 Windows 风格，如 `C:/nginx/logs/`）；
3. 把 `bcm.conf` 放到 `C:\nginx\conf\conf.d\`，并把 `root` 改成
   `C:/Users/32394/Desktop/BusinessCompetitionManagerWeb/BusinessCompetitionManagerWebFrontend/dist`；
4. `nginx -t` 通过后 `start nginx`（重载：`nginx -s reload`）。

> 本机没有安装 nginx，配置**未做 `nginx -t` 实测**；上面两种安装方式请在你的部署机验证一次。

## 3. 必须同步修改的 `.env` 配置

| 场景 | 设置 |
| --- | --- |
| 域名 | `ALLOWED_HOSTS='bcm.example.com'` |
| 前端跨域（若前后端不同源） | `CORS_ALLOWED_ORIGINS='https://bcm.example.com'` |
| HTTPS + 表单/CSRF | `CSRF_TRUSTED_ORIGINS='https://bcm.example.com'` |
| 反代后识别真实 IP | `TRUST_X_FORWARDED_FOR='true'`（仅信任自己的 nginx 时） |
| 反代终止 TLS | `TRUST_X_FORWARDED_PROTO='true'` |
| 强制 HTTPS | `SECURE_SSL_REDIRECT='true'`、`SECURE_HSTS_SECONDS='31536000'` |
| 上传上限 | nginx `client_max_body_size` 与 `UPLOAD_MAX_BYTES` / `PACKAGE_MAX_BYTES` 保持一致 |

## 4. 检查清单

- [ ] `nginx -t` 通过（语法）
- [ ] 首页能打开，刷新任意前端路由不 404（SPA 回退）
- [ ] `GET /api/health` 返回 200
- [ ] 浏览器能收到 WebSocket 推送（改一条数据，另一个页签自动刷新）
- [ ] 上传一个接近上限的文件能成功（验证 `client_max_body_size`）
- [ ] 访问日志里**看不到** `/ws/...?token=`（token 泄露防护）
- [ ] `https://` 下登录、改密、上传都正常（`COOKIE_SECURE`/CSRF 配置正确）

## 5. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| 刷新页面 404 | 缺 `try_files $uri $uri/ /index.html` |
| WebSocket 连不上（400/426） | `/ws/` 缺 `Upgrade`/`Connection` 头，或误把 `/ws` 代理到 8000 |
| 上传 413 | `client_max_body_size` 小于 `.env` 的上传上限 |
| 请求里 IP 全是 127.0.0.1 | 未开 `TRUST_X_FORWARDED_FOR`，或 nginx 没传 `X-Forwarded-For` |
| 登录后立刻 401 / 掉登录 | HTTPS 下 `SESSION_COOKIE_SECURE=true` 但实际是 HTTP，或 CSRF 受信源没配 |
| 推送延迟高 | `CHANNEL_POLL_INTERVAL` 偏大（默认 0.1s 足够） |
