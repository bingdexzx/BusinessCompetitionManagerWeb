#!/usr/bin/env python3
"""独立压测工具（不依赖 Django / 第三方库）。

用超管账号登录后，自动探测可访问的只读接口，按指定并发与思考时间发压，
最后输出控制台汇总 + Markdown/HTML 报告。

用法示例：
    python tools/loadtest/loadtest.py \
        --base-url http://127.0.0.1:8000 \
        --username full_admin --password '***' \
        --users 20 --duration 30 --think 1

不带参数则交互式询问网址 / 账号 / 密码。
"""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import random
import socket
import ssl
import statistics
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

THINK_JITTER = 0.3          # 思考时间抖动比例（±30%），避免所有线程同步


class ProgressBar:
    """终端进度条；非 TTY（CI/重定向）自动静默，避免日志刷屏。"""

    def __init__(self, total: float, label: str, width: int = 28):
        self.total = max(float(total), 0.001)
        self.label = label
        self.width = width
        self.enabled = sys.stdout.isatty()
        self._last_len = 0

    def render(self, current: float, detail: str = '') -> None:
        if not self.enabled:
            return
        ratio = max(0.0, min(1.0, current / self.total))
        filled = int(ratio * self.width)
        bar = '#' * filled + '-' * (self.width - filled)
        line = f'\r{self.label} [{bar}] {ratio * 100:5.1f}%  {detail[:70]}'
        pad = max(0, self._last_len - len(line))
        sys.stdout.write(line + ' ' * pad)
        sys.stdout.flush()
        self._last_len = len(line)

    def clear(self) -> None:
        if self.enabled and self._last_len:
            sys.stdout.write('\r' + ' ' * self._last_len + '\r')
            sys.stdout.flush()
        self._last_len = 0

    def finish(self, detail: str = '') -> None:
        self.render(self.total, detail)
        if self.enabled:
            sys.stdout.write('\n')
            sys.stdout.flush()
        self._last_len = 0


# ---------------------------------------------------------------- HTTP 客户端
class HttpClient:
    """HTTP/1.1 keep-alive 客户端（TCP_NODELAY；可复用连接，避免 Nagle 虚高）。"""

    def __init__(self, base_url: str, *, insecure: bool = False, timeout: float = 60):
        parsed = urlparse(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ValueError(f'网址不合法：{base_url}（示例 http://127.0.0.1:8000）')
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        self.timeout = timeout
        self.insecure = insecure
        self.conn = None

    def _connect(self):
        if self.scheme == 'https':
            context = ssl.create_default_context()
            if self.insecure:
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(
                self.host, self.port, timeout=self.timeout, context=context)
        else:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        conn.connect()
        try:
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        return conn

    def request(self, method: str, path: str, *, token: str = '', headers=None,
                body: dict | None = None):
        payload = None
        all_headers = {'Connection': 'keep-alive', 'Accept': 'application/json'}
        if token:
            all_headers['Authorization'] = f'Bearer {token}'
        if headers:
            all_headers.update(headers)
        if body is not None:
            payload = json.dumps(body).encode('utf-8')
            all_headers['Content-Type'] = 'application/json'

        for attempt in range(2):
            if self.conn is None:
                self.conn = self._connect()
            try:
                self.conn.request(method, path, body=payload, headers=all_headers)
                resp = self.conn.getresponse()
                data = resp.read()
                return resp.status, data
            except (http.client.HTTPException, OSError):
                try:
                    self.conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self.conn = None
                if attempt == 1:
                    raise
        raise RuntimeError('unreachable')

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001
                pass
            self.conn = None


# ---------------------------------------------------------------- 登录 / 探测
def api_login(client: HttpClient, username: str, password: str) -> dict:
    status, raw = client.request(
        'POST', '/api/auth/login', body={'username': username, 'password': password})
    text = raw.decode('utf-8', errors='replace')
    if status != 200:
        raise SystemExit(f'登录失败（HTTP {status}）：{text[:300]}')
    data = json.loads(text)
    if not data.get('access'):
        raise SystemExit(f'登录响应缺少 access 字段：{text[:300]}')
    return data


def pick_competition(client: HttpClient, token: str, cid: int | None) -> int | None:
    if cid:
        return cid
    status, raw = client.request('GET', '/api/competitions', token=token)
    if status != 200:
        return None
    data = json.loads(raw.decode('utf-8', errors='replace'))
    rows = data.get('items') if isinstance(data, dict) else data
    if not rows:
        return None
    # 优先已导入比赛包的比赛（数据更完整），否则取第一个
    for row in rows:
        if str(row.get('status') or '').upper() in ('PACKAGE_IMPORTED', 'ONGOING', 'RUNNING'):
            return int(row['id'])
    return int(rows[0]['id'])


def build_endpoints(cid: int | None) -> list[dict]:
    """候选只读接口（探测后只保留可用的）。"""
    endpoints = [
        {'label': '健康检查', 'method': 'GET', 'path': '/api/health', 'scope': False},
        {'label': '比赛列表', 'method': 'GET', 'path': '/api/competitions', 'scope': False},
        {'label': '当前用户', 'method': 'GET', 'path': '/api/me', 'scope': False},
    ]
    if not cid:
        return endpoints
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    endpoints += [
        {'label': '公司列表', 'method': 'GET',
         'path': f'/api/competitions/{cid}/companies', 'scope': True},
        {'label': '合同类型', 'method': 'GET',
         'path': f'/api/competitions/{cid}/contract-types', 'scope': True},
        {'label': '合同列表', 'method': 'GET',
         'path': f'/api/competitions/{cid}/contracts?page=1&pageSize=50', 'scope': True},
        {'label': '合同增量同步', 'method': 'GET',
         'path': f'/api/competitions/{cid}/contracts?updatedAfter={since}', 'scope': True},
        {'label': '股票行情', 'method': 'GET',
         'path': f'/api/competitions/{cid}/stock/stocks?page=1&pageSize=50', 'scope': True},
        {'label': '股票同步', 'method': 'GET',
         'path': f'/api/competitions/{cid}/stock/sync', 'scope': True},
        {'label': '基础数据(原料)', 'method': 'GET',
         'path': f'/api/competitions/{cid}/basedata/materials?page=1&pageSize=50', 'scope': True},
        {'label': '字段日志', 'method': 'GET',
         'path': f'/api/competitions/{cid}/logs/fields?page=1&pageSize=50', 'scope': True},
        {'label': '审计流水', 'method': 'GET',
         'path': f'/api/competitions/{cid}/audit-logs?page=1&pageSize=50', 'scope': True},
    ]
    return endpoints


def probe(client: HttpClient, token: str, endpoints: list[dict], cid: int | None,
          progress: ProgressBar | None = None) -> list[dict]:
    available = []
    total = len(endpoints)
    for index, endpoint in enumerate(endpoints, start=1):
        if progress:
            progress.render(index - 1, f'{index}/{total}  {endpoint["label"]}')
        headers = {'X-Competition-Id': str(cid)} if endpoint['scope'] and cid else {}
        try:
            status, _ = client.request(
                endpoint['method'], endpoint['path'], token=token, headers=headers)
        except Exception as exc:  # noqa: BLE001
            if progress:
                progress.clear()
            print(f'  [跳过] {endpoint["label"]}：{exc}')
            continue
        if progress:
            progress.clear()
        if status in (200, 201, 204):
            available.append(endpoint)
            print(f'  [可用] {endpoint["label"]}  HTTP {status}')
        else:
            print(f'  [跳过] {endpoint["label"]}  HTTP {status}')
    if progress:
        progress.clear()
    return available


# ---------------------------------------------------------------- 压测执行
class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.latencies: dict[str, list[float]] = {}
        self.statuses: dict[str, dict[int, int]] = {}
        self.errors: dict[str, int] = {}
        self.total = 0
        self.started_at = None
        self.ended_at = None

    def snapshot(self) -> tuple[int, int]:
        with self.lock:
            return self.total, sum(self.errors.values())

    def record(self, label: str, latency: float, status: int):
        with self.lock:
            self.latencies.setdefault(label, []).append(latency)
            bucket = self.statuses.setdefault(label, {})
            bucket[status] = bucket.get(status, 0) + 1
            if status == 0 or status >= 500:
                self.errors[label] = self.errors.get(label, 0) + 1
            self.total += 1


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def worker(base_url, insecure, endpoints, token_holder, stop_at, think, stats, cid,
           timeout=60):
    client = HttpClient(base_url, insecure=insecure, timeout=timeout)
    local_token = token_holder['token']
    headers_base = {'X-Competition-Id': str(cid)} if cid else {}
    try:
        while time.time() < stop_at:
            for endpoint in endpoints:
                if time.time() >= stop_at:
                    break
                headers = dict(headers_base) if endpoint['scope'] else {}
                started = time.perf_counter()
                status = 0
                try:
                    status, _ = client.request(
                        endpoint['method'], endpoint['path'],
                        token=local_token, headers=headers)
                    if status == 401:
                        # token 过期：重新登录一次（共享最新 token）
                        with token_holder['lock']:
                            if token_holder.get('credentials'):
                                username, password = token_holder['credentials']
                                try:
                                    data = api_login(client, username, password)
                                    local_token = data['access']
                                    token_holder['token'] = local_token
                                except SystemExit:
                                    pass
                except Exception:  # noqa: BLE001 —— 连接错误记 status 0
                    status = 0
                elapsed = (time.perf_counter() - started) * 1000
                stats.record(endpoint['label'], elapsed, status)
            time.sleep(max(0.0, think * (1 + random.uniform(-THINK_JITTER, THINK_JITTER))))
    finally:
        client.close()


# ---------------------------------------------------------------- 报告
def summarize(stats: Stats) -> dict:
    duration = (stats.ended_at - stats.started_at) if stats.started_at else 0
    rows = []
    all_latencies = []
    for label, latencies in stats.latencies.items():
        all_latencies.extend(latencies)
        statuses = stats.statuses.get(label, {})
        rows.append({
            'label': label,
            'count': len(latencies),
            'qps': len(latencies) / duration if duration else 0,
            'p50': percentile(latencies, 50),
            'p95': percentile(latencies, 95),
            'p99': percentile(latencies, 99),
            'max': max(latencies) if latencies else 0,
            'errors': stats.errors.get(label, 0),
            'statuses': statuses,
        })
    rows.sort(key=lambda row: row['p95'], reverse=True)
    total_errors = sum(stats.errors.values())
    return {
        'duration': duration,
        'total': stats.total,
        'qps': stats.total / duration if duration else 0,
        'errors': total_errors,
        'error_rate': total_errors / stats.total if stats.total else 0,
        'p50': percentile(all_latencies, 50),
        'p95': percentile(all_latencies, 95),
        'p99': percentile(all_latencies, 99),
        'rows': rows,
    }


def verdict(summary: dict) -> list[str]:
    notes = []
    if summary['errors']:
        notes.append(f'出现 {summary["errors"]} 个错误（5xx/连接失败），先查服务端日志与数据库连接数。')
    if summary['p95'] > 500:
        notes.append(f'整体 P95 = {summary["p95"]:.0f}ms，偏高：检查慢 SQL、N+1 与 DB 并发预算。')
    elif summary['p95'] > 200:
        notes.append(f'整体 P95 = {summary["p95"]:.0f}ms，可接受但接近阈值（建议 <200ms）。')
    else:
        notes.append(f'整体 P95 = {summary["p95"]:.0f}ms，处于健康区间（<200ms）。')
    if summary['total'] >= 300 and summary['p50'] > 0 and summary['p99'] / summary['p50'] > 5:
        notes.append('P99 远高于 P50（>5×）：存在排队/长尾，优先看连接池、线程数与锁等待。')
    if summary['qps']:
        notes.append(f'稳态吞吐约 {summary["qps"]:.1f} QPS（本次并发口径）。')
    return notes


def render_markdown(summary, config, endpoints) -> str:
    lines = [
        '# 压测报告',
        '',
        f'- 目标地址：`{config["base_url"]}`',
        f'- 登录账号：`{config["username"]}`（{config["role"]}）',
        f'- 比赛范围：`{config.get("cid") or "未指定"}`',
        f'- 开始时间：{config["started_at"]}',
        f'- 并发用户：{config["users"]}　思考时间：{config["think"]}s　持续：{config["duration"]}s',
        f'- 可用接口：{len(endpoints)} 个（{"、".join(e["label"] for e in endpoints)}）',
        '',
        '## 总体',
        '',
        '| 指标 | 数值 |',
        '| --- | --- |',
        f'| 总请求数 | {summary["total"]} |',
        f'| 吞吐 QPS | {summary["qps"]:.1f} |',
        f'| 错误数 / 错误率 | {summary["errors"]} / {summary["error_rate"] * 100:.2f}% |',
        f'| P50 | {summary["p50"]:.1f} ms |',
        f'| P95 | {summary["p95"]:.1f} ms |',
        f'| P99 | {summary["p99"]:.1f} ms |',
        '',
        '## 分接口',
        '',
        '| 接口 | 请求数 | QPS | P50 | P95 | P99 | Max | 错误 | 状态码 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |',
    ]
    for row in summary['rows']:
        statuses = ', '.join(f'{code}×{count}' for code, count in sorted(row['statuses'].items()))
        lines.append(
            f'| {row["label"]} | {row["count"]} | {row["qps"]:.1f} | '
            f'{row["p50"]:.1f} | {row["p95"]:.1f} | {row["p99"]:.1f} | '
            f'{row["max"]:.1f} | {row["errors"]} | {statuses} |')
    lines += ['', '## 结论与建议', '']
    lines += [f'- {note}' for note in verdict(summary)]
    lines += ['', f'> 生成时间：{datetime.now().astimezone().isoformat(timespec="seconds")}', '']
    return '\n'.join(lines)


def render_html(markdown_text: str, summary) -> str:
    rows = ''.join(
        f'<tr><td>{row["label"]}</td><td>{row["count"]}</td><td>{row["qps"]:.1f}</td>'
        f'<td>{row["p50"]:.1f}</td><td>{row["p95"]:.1f}</td><td>{row["p99"]:.1f}</td>'
        f'<td>{row["max"]:.1f}</td><td>{row["errors"]}</td></tr>'
        for row in summary['rows'])
    notes = ''.join(f'<li>{note}</li>' for note in verdict(summary))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>压测报告</title>
<style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;margin:32px;color:#1f2937}}
h1{{font-size:22px}} table{{border-collapse:collapse;width:100%;margin:12px 0}}
th,td{{border:1px solid #e5e7eb;padding:8px 10px;text-align:right;font-size:13px}}
th{{background:#f9fafb}} td:first-child,th:first-child{{text-align:left}}
.kpi{{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}}
.kpi div{{border:1px solid #e5e7eb;border-radius:8px;padding:12px 16px;min-width:140px}}
.kpi b{{display:block;font-size:20px}}
</style></head><body>
<h1>压测报告</h1>
<div class="kpi">
<div>总请求<b>{summary['total']}</b></div>
<div>QPS<b>{summary['qps']:.1f}</b></div>
<div>P95<b>{summary['p95']:.0f} ms</b></div>
<div>P99<b>{summary['p99']:.0f} ms</b></div>
<div>错误<b>{summary['errors']}</b></div>
</div>
<table><thead><tr><th>接口</th><th>请求数</th><th>QPS</th><th>P50</th><th>P95</th>
<th>P99</th><th>Max</th><th>错误</th></tr></thead><tbody>{rows}</tbody></table>
<h2>结论与建议</h2><ul>{notes}</ul>
<pre style="white-space:pre-wrap;color:#6b7280;font-size:12px">{markdown_text[:4000]}</pre>
</body></html>"""


def write_reports(summary, config, endpoints, report_dir: str, make_html: bool) -> tuple[str, str | None]:
    try:
        os.makedirs(report_dir, exist_ok=True)
    except OSError:
        # 目标目录不可写（例如脚本放在只读位置）：退回用户目录，保证「放哪都能跑」
        report_dir = os.path.join(os.path.expanduser('~'), 'bcm_loadtest_reports')
        os.makedirs(report_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    markdown_path = os.path.join(report_dir, f'loadtest_{stamp}.md')
    markdown_text = render_markdown(summary, config, endpoints)
    with open(markdown_path, 'w', encoding='utf-8') as fh:
        fh.write(markdown_text)
    html_path = None
    if make_html:
        html_path = os.path.join(report_dir, f'loadtest_{stamp}.html')
        with open(html_path, 'w', encoding='utf-8') as fh:
            fh.write(render_html(markdown_text, summary))
    return markdown_path, html_path


# ---------------------------------------------------------------- 入口
def _ask_number(label: str, default, cast):
    raw = input(f'{label}（默认 {default}）：').strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        print(f'  输入无效，使用默认值 {default}')
        return default


def prompt_if_missing(args):
    if not args.base_url:
        args.base_url = input('目标网址（如 http://127.0.0.1:8000）：').strip()
    if not args.username:
        args.username = input('超级管理员账号：').strip()
    if not args.password:
        args.password = getpass.getpass('密码（输入不回显）：')
    # 并发/时长/思考时间：未显式传参时交互询问；--yes 或非交互环境用默认值
    interactive = sys.stdin.isatty() and not args.yes
    if args.users is None:
        args.users = (_ask_number('并发用户数', 10, int) if interactive else 10)
    if args.duration is None:
        args.duration = (_ask_number('持续压测秒数', 30, float) if interactive else 30.0)
    if args.think is None:
        args.think = (_ask_number('每轮思考时间（秒）', 1.0, float) if interactive else 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description='独立压测工具（只读接口）')
    parser.add_argument('--base-url', help='目标网址，如 http://127.0.0.1:8000')
    parser.add_argument('--username', help='超级管理员账号')
    parser.add_argument('--password', help='密码（不传则交互输入）')
    parser.add_argument('--users', type=int, default=None,
                        help='并发虚拟用户数（不传则交互询问，默认 10）')
    parser.add_argument('--duration', type=float, default=None,
                        help='持续压测秒数（不传则交互询问，默认 30）')
    parser.add_argument('--think', type=float, default=None,
                        help='每轮请求后的思考时间（秒，不传则交互询问，默认 1）')
    parser.add_argument('--timeout', type=float, default=60.0,
                        help='单请求超时秒数（默认 60）')
    parser.add_argument('--cid', type=int, help='指定比赛 ID（默认自动挑选）')
    parser.add_argument('--report-dir', default='reports/loadtest', help='报告输出目录')
    parser.add_argument('--insecure', action='store_true', help='HTTPS 忽略证书校验')
    parser.add_argument('--no-html', action='store_true', help='只生成 Markdown 报告')
    parser.add_argument('--yes', action='store_true', help='跳过开始前确认')
    parser.add_argument('--fail-on-error', action='store_true', help='有错误时退出码非 0')
    args = parser.parse_args()

    prompt_if_missing(args)
    if not args.base_url or not args.username or not args.password:
        parser.error('缺少网址 / 账号 / 密码')
    if args.users < 1:
        parser.error('并发数必须 ≥ 1')
    if args.duration <= 0:
        parser.error('压测时长必须 > 0 秒')
    if args.think < 0:
        parser.error('思考时间不能为负数')
    if args.timeout <= 0:
        parser.error('请求超时必须 > 0 秒')

    print(f'\n目标：{args.base_url}　账号：{args.username}')
    print(f'计划：{args.users} 并发 × {args.duration}s（思考 {args.think}s）')
    if not args.yes:
        confirm = input('将产生真实请求，确认开始？[y/N] ').strip().lower()
        if confirm not in ('y', 'yes'):
            print('已取消')
            return 0

    client = HttpClient(args.base_url, insecure=args.insecure, timeout=args.timeout)
    try:
        print('正在登录…')
        login_data = api_login(client, args.username, args.password)
        token = login_data['access']
        user = login_data.get('user') or {}
        role = '超级管理员' if user.get('isSuperuser') else (user.get('username') or '已登录用户')
        print(f'✓ 登录成功：{user.get("username") or args.username}（{role}）')

        cid = pick_competition(client, token, args.cid)
        print(f'✓ 比赛范围：{cid or "未指定（仅全局接口）"}')

        print('探测接口：')
        candidates = build_endpoints(cid)
        endpoints = probe(client, token, candidates, cid,
                          ProgressBar(len(candidates), '探测'))
        if not endpoints:
            print('没有可用的只读接口，终止')
            return 2
    finally:
        client.close()

    stats = Stats()
    token_holder = {'token': token, 'lock': threading.Lock(),
                    'credentials': (args.username, args.password)}
    stats.started_at = time.time()
    stop_at = stats.started_at + args.duration
    config = {
        'base_url': args.base_url,
        'username': args.username,
        'role': role,
        'cid': cid,
        'started_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'users': args.users,
        'think': args.think,
        'duration': args.duration,
    }

    threads = [
        threading.Thread(
            target=worker,
            args=(args.base_url, args.insecure, endpoints, token_holder,
                  stop_at, args.think, stats, cid, args.timeout),
            daemon=True,
        )
        for _ in range(max(1, args.users))
    ]
    for thread in threads:
        thread.start()
    progress = ProgressBar(args.duration, '压测')
    while True:
        now = time.time()
        elapsed = min(now - stats.started_at, args.duration)
        total, errors = stats.snapshot()
        progress.render(
            elapsed,
            f'{elapsed:0.0f}/{args.duration:.0f}s  请求 {total}  错误 {errors}  '
            f'QPS {total / max(elapsed, 0.5):.1f}',
        )
        if now >= stop_at and not any(thread.is_alive() for thread in threads):
            break
        time.sleep(0.25)
    for thread in threads:
        thread.join()
    stats.ended_at = time.time()
    progress.finish(f'{args.duration:.0f}s 完成')

    summary = summarize(stats)
    print('\n=== 压测结果 ===')
    print(f'总请求 {summary["total"]}　QPS {summary["qps"]:.1f}　'
          f'错误 {summary["errors"]}（{summary["error_rate"] * 100:.2f}%）')
    print(f'P50 {summary["p50"]:.1f}ms　P95 {summary["p95"]:.1f}ms　P99 {summary["p99"]:.1f}ms')
    print(f'{"接口":<18}{"请求":>7}{"QPS":>8}{"P50":>9}{"P95":>9}{"P99":>9}{"错误":>6}')
    for row in summary['rows']:
        print(f'{row["label"]:<18}{row["count"]:>7}{row["qps"]:>8.1f}'
              f'{row["p50"]:>9.1f}{row["p95"]:>9.1f}{row["p99"]:>9.1f}{row["errors"]:>6}')
    print('\n结论：')
    for note in verdict(summary):
        print(f'  - {note}')

    markdown_path, html_path = write_reports(
        summary, config, endpoints, args.report_dir, not args.no_html)
    print(f'\n报告已生成：\n  {markdown_path}')
    if html_path:
        print(f'  {html_path}')

    if args.fail_on_error and summary['errors']:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
