# 独立压测工具（单文件 .bat）

**只需要 Windows 的 cmd + Python 3.10+**，不依赖 Django、不装任何第三方包，
放在任意目录、从任意位置运行都可以（报告写在 bat 旁边的 `reports\loadtest`）。

## 快速开始

1. 双击 **`loadtest.bat`**（或在 cmd 里直接运行 `loadtest.bat`）；
2. 按提示输入：目标网址 → 超管账号 → 密码（输入不回显）→ 并发数 → 持续秒数 → 思考时间；
3. 探测接口与压测过程中会显示实时进度条；
4. 跑完在 `loadtest.bat` 同目录的 `reports\loadtest\` 下生成 Markdown + HTML 报告。

也可以直接带参数（适合脚本/CI，写在 cmd 里）：

```bat
loadtest.bat --base-url http://127.0.0.1:8000 ^
  --username full_admin --password "***" ^
  --users 20 --duration 60 --think 1 --timeout 30 --yes
```

> 只要系统有 `py` 启动器或 `python` 在 PATH 里即可；脚本会优先用 `py -3`，
> 避免命中 Microsoft Store 的 python 占位符。

## 参数

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `--base-url` | 目标网址（http/https） | 交互询问 |
| `--username` | 超级管理员账号 | 交互询问 |
| `--password` | 密码（建议交互输入，避免进历史） | 交互询问 |
| `--users` | 并发虚拟用户数 | 交互询问，默认 10 |
| `--duration` | 持续压测秒数 | 交互询问，默认 30 |
| `--think` | 每轮请求后的思考时间（秒） | 交互询问，默认 1.0 |
| `--timeout` | 单请求超时秒数 | 60 |
| `--cid` | 指定比赛 ID | 自动挑第一个可用比赛 |
| `--report-dir` | 报告目录（bat 默认传脚本旁 `reports\loadtest`） | 脚本旁 |
| `--insecure` | HTTPS 忽略证书校验 | 关闭 |
| `--no-html` | 只生成 Markdown | 关闭 |
| `--yes` | 跳过开始前确认 | 关闭 |
| `--fail-on-error` | 有错误时退出码非 0（CI 门禁） | 关闭 |

## 进度与反馈

- 登录后先显示 `探测 [####----] 42%  3/8 合同列表`；
- 压测开始后显示实时进度：`压测 [######----] 60%  18/30s  请求 952  错误 0  QPS 52.1`；
- 非 TTY 环境（CI、重定向到文件）自动关闭进度条，避免日志刷屏；
- 指定 `--yes` 时使用默认并发/时长，不交互询问。

## 压测哪些接口

登录后自动探测，**只保留返回 200 的只读接口**，不写任何数据：

- 健康检查 `/api/health`
- 比赛列表 `/api/competitions`
- 当前用户 `/api/me`
- 公司列表、合同类型、合同列表、合同增量同步
- 股票行情、股票同步
- 基础数据（原料）
- 字段日志、审计流水（路由不存在时自动跳过）

## 报告

```
reports\loadtest\loadtest_20261125_160100.md    # 文本（可贴群/入库）
reports\loadtest\loadtest_20261125_160100.html  # 浏览器直接打开
```

内容：目标/账号/比赛/并发/思考时间 → 总体指标（QPS、错误率、P50/P95/P99）
→ 分接口表（含状态码分布）→ 自动结论与建议。

## 实现说明（维护用）

- `loadtest.bat` 是**单文件版**：前半段是批处理（找 Python → 用 PowerShell 把内嵌源码抽到
  `%TEMP%` 执行 → 删除临时文件），后半段是完整的 Python 源码；
- 源码在 `loadtest.py`；修改后运行 `python build_bat.py` 重新生成 `.bat`；
- 报告目录不可写时（如 bat 放在只读位置），会自动退回 `%USERPROFILE%\bcm_loadtest_reports`。

## 注意

- 只读压测（全 GET），不会创建/修改/删除数据；
- 默认 10 并发 × 30s，建议先小规模试跑再逐步加压；
- 压测时后端请用 `run_servers.py --no-reload`（开发热重载会中途重启 worker，长尾数据不准）；
- 超管密码不要写进脚本/仓库，建议交互输入。
