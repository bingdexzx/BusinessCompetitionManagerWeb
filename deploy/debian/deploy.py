#!/usr/bin/env python3
"""BCM 部署与运维脚本（Debian，v2）。

设计目标：**能自动判断的都自动判断，只问真正需要人决定的**；重复执行安全（幂等），
失败时给出可操作的下一步。

用法：
    sudo python3 deploy/debian/deploy.py                 # 交互式安装（默认 install）
    sudo python3 deploy/debian/deploy.py install --yes   # 全自动安装（自动探测 IP）
    sudo python3 deploy/debian/deploy.py upgrade         # 已部署环境升级（代码/依赖/迁移/前端/重启）
    python3 deploy/debian/deploy.py doctor               # 只体检，不改系统
    python3 deploy/debian/deploy.py status               # 看服务/健康/端口/配置摘要

常用参数见 `--help`；`--dry-run` 只打印计划。
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = 'bcm'
SERVICE_USER = 'bcm'
HTTP_PORT = 8000
WS_PORT = 8001
UV_DIR = '/opt/uv-python'



# ---------------------------------------------------------------- UI
class UI:
    ok_color = '\033[32m'
    warn_color = '\033[33m'
    err_color = '\033[31m'
    info_color = '\033[36m'
    bold = '\033[1m'
    end = '\033[0m'

    enabled = sys.stdout.isatty()

    @classmethod
    def _c(cls, color: str, text: str) -> str:
        return f'{color}{text}{cls.end}' if cls.enabled else text

    @classmethod
    def step(cls, title: str) -> None:
        print('\n' + cls._c(cls.bold, f'== {title} ' + '=' * max(0, 58 - len(title))))

    @classmethod
    def ok(cls, text: str) -> None:
        print(cls._c(cls.ok_color, '[完成]') + f' {text}')

    @classmethod
    def warn(cls, text: str) -> None:
        print(cls._c(cls.warn_color, '[注意]') + f' {text}')

    @classmethod
    def info(cls, text: str) -> None:
        print(cls._c(cls.info_color, '[信息]') + f' {text}')

    @classmethod
    def fail(cls, text: str) -> None:
        print(cls._c(cls.err_color, '[失败]') + f' {text}')


class Abort(Exception):
    pass


def die(message: str) -> None:
    UI.fail(message)
    raise Abort(message)


def ask(question: str, default: str = '', *, required: bool = False,
        secret: bool = False) -> str:
    hint = f'（默认：{default}）' if default else ''
    while True:
        value = (getpass.getpass(f'{question}{hint}：') if secret
                 else input(f'{question}{hint}：')).strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ''
        UI.warn('不能为空')


def confirm(question: str, default: bool = True) -> bool:
    raw = input(f'{question} {"[Y/n]" if default else "[y/N]"}：').strip().lower()
    return default if not raw else raw in ('y', 'yes', '是')


# ---------------------------------------------------------------- Runner
class Runner:
    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose

    def run(self, cmd, *, cwd=None, env=None, check=True, capture=False):
        printable = ' '.join(str(part) for part in cmd)
        if self.dry_run:
            UI.info(f'[dry-run] {printable}')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if self.verbose:
            UI.info(printable)
        result = subprocess.run(
            [str(part) for part in cmd],
            cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})},
            capture_output=capture, text=True,
        )
        if check and result.returncode != 0:
            detail = ((result.stderr or '') + (result.stdout or '')).strip()
            die(f'命令执行失败（{result.returncode}）：{printable}\n{detail[-1500:]}')
        return result

    def capture(self, cmd, *, cwd=None, env=None, check=False):
        return self.run(cmd, cwd=cwd, env=env, check=check, capture=True)


# ---------------------------------------------------------------- 事实探测
@dataclass
class Facts:
    debian: bool = False
    root: bool = False
    onepanel: bool = False
    openresty: bool = False
    system_nginx: bool = False
    postgres_port: bool = False
    certbot: bool = False
    node: bool = False
    uv: str = ''
    python: str = ''
    disk_free_gb: float = 0.0
    memory_gb: float = 0.0
    cpu_count: int = 1
    local_ip: str = ''


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def detect_primary_ip() -> str:
    try:
        out = subprocess.run(['ip', '-4', 'route', 'get', '1.1.1.1'],
                             capture_output=True, text=True, timeout=3).stdout.split()
        if 'src' in out and not out[out.index('src') + 1].startswith('127.'):
            return out[out.index('src') + 1]
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(['hostname', '-I'], capture_output=True, text=True,
                             timeout=3).stdout.split()
        for ip in out:
            if ip and not ip.startswith('127.'):
                return ip
    except Exception:  # noqa: BLE001
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        return '' if ip.startswith('127.') else ip
    except OSError:
        return ''


def disk_free_gb() -> float:
    try:
        usage = shutil.disk_usage(str(ROOT))
        return usage.free / 1024 ** 3
    except OSError:
        return 0.0


def memory_gb() -> float:
    try:
        text = Path('/proc/meminfo').read_text(encoding='utf-8')
        match = re.search(r'^MemTotal:\s+(\d+)', text, re.M)
        return int(match.group(1)) / 1024 ** 2 if match else 0.0
    except OSError:
        return 0.0


def detect() -> Facts:
    facts = Facts()
    try:
        os_release = Path('/etc/os-release').read_text(encoding='utf-8', errors='replace')
        facts.debian = 'ID=debian' in os_release or 'ID_LIKE=debian' in os_release
    except OSError:
        pass
    facts.root = os.geteuid() == 0 if hasattr(os, 'geteuid') else False
    facts.onepanel = Path('/opt/1panel').exists() or bool(shutil.which('1pctl'))
    facts.openresty = bool(shutil.which('openresty')) or Path('/usr/local/openresty').exists()
    facts.system_nginx = bool(shutil.which('nginx')) or Path('/usr/sbin/nginx').exists()
    facts.postgres_port = port_open('127.0.0.1', 5432)
    facts.certbot = bool(shutil.which('certbot'))
    facts.node = bool(shutil.which('node'))
    facts.uv = shutil.which('uv') or ''
    facts.python = shutil.which('python3') or ''
    facts.disk_free_gb = disk_free_gb()
    facts.memory_gb = memory_gb()
    facts.cpu_count = os.cpu_count() or 1
    facts.local_ip = detect_primary_ip()
    return facts


def show_facts(facts: Facts) -> None:
    checks = [
        ('Debian 系统', facts.debian),
        ('root 权限', facts.root),
        ('1Panel', facts.onepanel),
        ('OpenResty', facts.openresty),
        ('系统 Nginx', facts.system_nginx),
        ('PostgreSQL（5432 监听）', facts.postgres_port),
        ('Node.js', facts.node),
        ('certbot', facts.certbot),
        ('uv', bool(facts.uv)),
    ]
    for label, value in checks:
        print(f'  {"✓" if value else "·"} {label}')
    print(f'  磁盘可用：{facts.disk_free_gb:.1f} GB　内存：{facts.memory_gb:.1f} GB'
          f'　CPU：{facts.cpu_count} 核')
    if facts.local_ip:
        print(f'  本机 IP：{facts.local_ip}')


# ---------------------------------------------------------------- 配置
@dataclass
class Config:
    mode: str = 'install'
    domain: str = ''
    ip_mode: bool = False
    app_dir: str = '/opt/bcm'
    site_dir: str = ''
    admin_user: str = 'admin'
    admin_email: str = 'admin@example.com'
    admin_password: str = ''
    reset_admin: bool = False
    force_cert: bool = False
    pgbouncer: bool = True          # 部署时自动启动 PgBouncer（--no-pgbouncer 关闭）
    db_mode: str = 'auto'          # auto | local | existing
    db_name: str = 'business_competition_manager'
    db_user: str = 'bcm_app'
    db_password: str = ''
    db_host: str = '127.0.0.1'
    db_port: str = '5432'
    workers: int = 4
    threads: int = 8
    db_tune: bool = True
    db_max_requests: int = 32
    db_max_connections: int = 100
    pg_shared_buffers_mb: int = 256
    pg_effective_cache_mb: int = 1024
    pg_work_mem_mb: int = 8
    pg_maintenance_mem_mb: int = 128
    pg_wal_buffers_mb: int = 16
    pgb_max_client: int = 200
    pgb_pool_size: int = 30
    pgb_reserve_pool: int = 5
    http_port: int = 80
    nginx_mode: str = 'system'     # 默认系统 nginx；manage | manual 可覆盖
    stop_openresty: bool = False
    tls: bool | None = None
    build_frontend: bool = True
    firewall: bool | None = None
    secret_key: str = ''
    dry_run: bool = False
    yes: bool = False
    verbose: bool = False
    facts: Facts = field(default_factory=Facts)


def _clamp(value: float, low: float, high: float) -> int:
    return int(max(low, min(high, value)))


def _set_capacity(cfg: Config, workers: int, threads: int) -> None:
    """按已确定的 worker/线程数，推导 DB/PgBouncer 参数。"""
    cpu = max(1, cfg.facts.cpu_count or os.cpu_count() or 1)
    mem = max(0.5, cfg.facts.memory_gb or 1.0)
    workers = max(1, int(workers))
    threads = max(1, int(threads))
    if workers * threads > 96:
        threads = max(4, 96 // workers)

    total_threads = workers * threads
    db_max_requests = max(8, total_threads)
    db_max_connections = _clamp(total_threads * 2 + 20, 50, 500)

    # PostgreSQL 内存参数（只在 local 模式应用）
    shared = _clamp(mem * 1024 * 0.25, 128, 8192)
    effective = _clamp(mem * 1024 * 0.60, 256, 16384)
    maintenance = _clamp(mem * 1024 * 0.05, 64, 1024)
    work = _clamp(mem * 1024 * 0.02 / max(8, total_threads // 2), 4, 32)
    wal = _clamp(shared / 32, 8, 64)

    # PgBouncer：客户端连接要覆盖应用线程，服务端池可小于客户端
    max_client = _clamp(total_threads * 2 + 50, 100, 2000)
    pool = _clamp(total_threads // 2, 10, 100)
    reserve = max(5, pool // 4)

    cfg.workers = workers
    cfg.threads = threads
    cfg.db_max_requests = db_max_requests
    cfg.db_max_connections = db_max_connections
    cfg.pg_shared_buffers_mb = shared
    cfg.pg_effective_cache_mb = effective
    cfg.pg_work_mem_mb = work
    cfg.pg_maintenance_mem_mb = maintenance
    cfg.pg_wal_buffers_mb = wal
    cfg.pgb_max_client = max_client
    cfg.pgb_pool_size = pool
    cfg.pgb_reserve_pool = reserve
    UI.info(f'自动参数：{workers} worker × {threads} 线程，'
            f'DB 并发 {db_max_requests}，max_connections {db_max_connections}，'
            f'shared_buffers {shared}MB，PgBouncer 池 {pool}')


def apply_hardware_profile(cfg: Config, args) -> None:
    """按 CPU / 内存推导进程、连接与 PostgreSQL/PgBouncer 参数。

    原则：小机器保守、大机器逐步放开；显式 --workers/--threads 优先。
    数据库连接预算按「每请求最多占全局库+比赛库 2 条连接」估算。
    """
    cpu = max(1, cfg.facts.cpu_count or os.cpu_count() or 1)
    mem = max(0.5, cfg.facts.memory_gb or 1.0)
    workers = int(args.workers) if args.workers else min(cpu, 8)
    threads = int(args.threads) if args.threads else (8 if mem >= 1.5 else 4)
    _set_capacity(cfg, workers, threads)

def is_ip(value: str) -> bool:
    import ipaddress
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def read_env(path: Path) -> dict:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        match = re.match(r'^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$', line)
        if not match:
            continue
        value = match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[match.group(1)] = value
    return values


def env_value(env: dict, key: str, default: str = '') -> str:
    return env.get(key, default)


def collect(args, facts: Facts, env_path: Path) -> Config:
    existing = read_env(env_path) if args.mode == 'upgrade' or env_path.exists() else {}
    cfg = Config(mode=args.mode, facts=facts, dry_run=args.dry_run, yes=args.yes,
                 verbose=args.verbose, app_dir=args.app_dir or '/opt/bcm')

    if cfg.mode == 'upgrade':
        if not env_path.exists():
            die(f'升级模式需要已有的 .env：{env_path} 不存在')
        UI.info(f'升级模式：沿用 {env_path} 的数据库连接与密钥')
        cfg.secret_key = env_value(existing, 'SECRET_KEY')
        cfg.db_name = env_value(existing, 'DATABASES_NAME', cfg.db_name)
        cfg.db_user = env_value(existing, 'DATABASES_USER', cfg.db_user)
        cfg.db_password = env_value(existing, 'DATABASES_PASSWORD')
        cfg.db_host = env_value(existing, 'DATABASES_HOST', cfg.db_host)
        cfg.db_port = env_value(existing, 'DATABASES_PORT', cfg.db_port)
        cfg.site_dir = args.site_dir or ''
        cfg.nginx_mode = 'skip'
        cfg.db_tune = not bool(args.no_db_tune)
        cfg.workers = int(args.workers or env_value(
            existing, 'WEB_CONCURRENCY', str(min(os.cpu_count() or 1, 8))))
        cfg.threads = int(args.threads or 8)
        _set_capacity(cfg, cfg.workers, cfg.threads)
        return cfg

    # ---- 访问地址（域名或 IP）
    address = args.ip or args.domain
    if not address:
        if cfg.yes:
            address = facts.local_ip
            if not address:
                die('--yes 需要 --domain 或 --ip（未能自动探测本机 IP）')
            UI.warn(f'未指定地址，自动使用本机 IP：{address}（公网不同请用 --ip）')
        else:
            address = ask('站点域名或公网 IP', facts.local_ip, required=True)
    cfg.domain = address
    cfg.ip_mode = is_ip(address)
    if cfg.ip_mode:
        UI.info('纯 IP 模式：HTTP 访问，不做 HTTPS 证书')

    # ---- 安装目录 / 站点目录
    raw = args.app_dir or ('/opt/bcm' if cfg.yes else ask('安装目录', '/opt/bcm'))
    if sys.platform == 'linux':
        cfg.app_dir = str(Path(raw).expanduser().resolve())
    else:
        cfg.app_dir = raw.rstrip('/') or '/opt/bcm'
    if cfg.app_dir == str(ROOT):
        UI.info('安装目录与源码目录相同（就地部署）')
    raw_site = args.site_dir or ''
    cfg.site_dir = str(Path(raw_site).expanduser().resolve()).rstrip('/') if raw_site else ''

    # ---- 管理员
    cfg.admin_user = args.admin_user or ('admin' if cfg.yes else ask('管理员用户名', 'admin'))
    default_email = 'admin@example.com' if cfg.ip_mode else f'admin@{cfg.domain}'
    cfg.admin_email = args.admin_email or (default_email if cfg.yes
                                           else ask('管理员邮箱', default_email))
    cfg.admin_password = args.admin_password or ''
    if not cfg.admin_password:
        if cfg.yes:
            cfg.admin_password = gen_token(12)
            UI.info('管理员初始密码已自动生成')
        elif confirm('管理员密码自动生成？', True):
            cfg.admin_password = gen_token(12)
        else:
            cfg.admin_password = ask('管理员密码', secret=True, required=True)
    cfg.reset_admin = bool(args.reset_admin_password)
    cfg.force_cert = bool(args.force_cert)
    cfg.pgbouncer = bool(args.pgbouncer)
    cfg.db_tune = not bool(args.no_db_tune)

    # ---- 数据库
    reuse = bool(existing.get('DATABASES_PASSWORD')) and not args.db_password
    if args.db_mode:
        cfg.db_mode = args.db_mode
    elif reuse:
        cfg.db_mode = 'existing'
    elif facts.postgres_port:
        cfg.db_mode = 'existing' if (cfg.yes or confirm(
            '检测到本机 PostgreSQL 已在运行，直接使用它？', True)) else 'local'
    elif cfg.yes:
        cfg.db_mode = 'local'
    else:
        cfg.db_mode = ask('数据库模式（local=本机安装 / existing=已有库）', 'local')

    if reuse:
        cfg.db_name = args.db_name or env_value(existing, 'DATABASES_NAME', cfg.db_name)
        cfg.db_user = args.db_user or env_value(existing, 'DATABASES_USER', cfg.db_user)
        cfg.db_password = env_value(existing, 'DATABASES_PASSWORD')
        cfg.db_host = args.db_host or env_value(existing, 'DATABASES_HOST', cfg.db_host)
        cfg.db_port = args.db_port or env_value(existing, 'DATABASES_PORT', cfg.db_port)
        cfg.secret_key = env_value(existing, 'SECRET_KEY')
        UI.info('复用已有 .env 的数据库连接与 SECRET_KEY（升级不会改密/掉登录）')

    if cfg.db_mode == 'existing' and not reuse:
        cfg.db_host = args.db_host or (ask('数据库主机', '127.0.0.1') if not cfg.yes else '127.0.0.1')
        cfg.db_port = args.db_port or (ask('数据库端口', '5432') if not cfg.yes else '5432')
        cfg.db_name = args.db_name or (ask('数据库名', cfg.db_name) if not cfg.yes else cfg.db_name)
        cfg.db_user = args.db_user or (ask('数据库用户', cfg.db_user) if not cfg.yes else cfg.db_user)
        cfg.db_password = args.db_password or (ask('数据库密码', secret=True, required=True)
                                               if not cfg.yes else '')
    if cfg.db_mode == 'local' and not reuse:
        cfg.db_name = args.db_name or (ask('将创建的数据库名', cfg.db_name) if not cfg.yes
                                       else cfg.db_name)
        cfg.db_user = args.db_user or (ask('将创建的数据库用户', cfg.db_user) if not cfg.yes
                                       else cfg.db_user)
        cfg.db_password = args.db_password or gen_token(24)

    if not cfg.db_password:
        die('缺少数据库密码：请用 --db-password 提供，或在 1Panel 创建库后重试')

    apply_hardware_profile(cfg, args)
    if not cfg.yes:
        cfg.workers = int(ask('worker 进程数', str(cfg.workers)))
        cfg.threads = int(ask('每 worker 线程数', str(cfg.threads)))
        _set_capacity(cfg, cfg.workers, cfg.threads)

    # ---- nginx 模式：默认就是系统 nginx（不再依赖 1Panel/OpenResty 的判断）
    cfg.nginx_mode = args.nginx_mode or 'system'
    if cfg.nginx_mode == 'system' and (facts.onepanel or facts.openresty):
        UI.info('默认使用系统 nginx；若 80 被 1Panel OpenResty 占用，'
                '脚本会停掉它或自动改用 8080')

    if cfg.nginx_mode == 'manual':
        cfg.tls = False
    else:
        # 域名模式默认自动申请证书；--no-tls 可关闭
        cfg.tls = args.tls if args.tls is not None else (False if cfg.ip_mode else True)
        if cfg.tls:
            UI.info('将自动申请 Let\'s Encrypt 证书（失败会回退 HTTP 并提示）')
    cfg.http_port = int(args.http_port or (80 if cfg.yes else ask('nginx 监听端口', '80')))
    cfg.stop_openresty = bool(args.stop_openresty)

    cfg.build_frontend = args.build_frontend if args.build_frontend is not None else (
        True if cfg.yes else confirm('在本机构建前端？', True))
    if cfg.firewall is None:
        cfg.firewall = bool(args.firewall) if args.firewall is not None else (
            False if facts.onepanel else (True if cfg.yes else confirm(
                '启用 ufw 防火墙（放行 SSH/80/443）？', True)))
    else:
        cfg.firewall = bool(cfg.firewall)
    if args.firewall is not None:
        cfg.firewall = bool(args.firewall)

    if not cfg.secret_key:
        cfg.secret_key = gen_token(48)
    return cfg


def gen_token(length: int) -> str:
    import secrets
    return secrets.token_urlsafe(length)


# ---------------------------------------------------------------- 前置检查
def preflight(cfg: Config) -> None:
    if cfg.dry_run:
        return
    if sys.platform != 'linux':
        die('只能在 Debian Linux 上执行（可用 --dry-run 预演）')
    if not cfg.facts.debian:
        die('当前系统不是 Debian（/etc/os-release 未匹配）')
    if not cfg.facts.root:
        die('请用 root 执行：sudo python3 deploy/debian/deploy.py')
    if cfg.facts.disk_free_gb and cfg.facts.disk_free_gb < 2:
        die(f'磁盘可用空间不足 2GB（当前 {cfg.facts.disk_free_gb:.1f}GB）')
    if cfg.facts.memory_gb and cfg.facts.memory_gb < 1.5:
        UI.warn(f'内存较小（{cfg.facts.memory_gb:.1f}GB），建议 ≥2GB')


# ---------------------------------------------------------------- .env
def render_env(cfg: Config) -> str:
    secure = 'true' if (cfg.tls and not cfg.ip_mode) else 'false'
    proto = 'https' if secure == 'true' else 'http'
    db_max = cfg.db_max_requests
    return f"""# 由 deploy/debian/deploy.py 生成（{time.strftime('%Y-%m-%d %H:%M:%S')}）
APP_VERSION = '1.0.0'
DEBUG = 'false'

DATABASES_NAME = '{cfg.db_name}'
DATABASES_USER = '{cfg.db_user}'
DATABASES_PASSWORD = '{cfg.db_password}'
DATABASES_HOST = '{cfg.db_host}'
DATABASES_PORT = '{cfg.db_port}'
DATABASES_CONN_MAX_AGE = '60'
DATABASES_CONNECT_TIMEOUT = '5'

SECRET_KEY = '{cfg.secret_key}'

ALLOWED_HOSTS = '{cfg.domain}'
CORS_ALLOWED_ORIGINS = '{proto}://{cfg.domain}'
CSRF_TRUSTED_ORIGINS = '{proto}://{cfg.domain}'
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_SSL_REDIRECT = '{secure}'
SECURE_HSTS_SECONDS = '{'31536000' if secure == 'true' else '0'}'
SECURE_HSTS_PRELOAD = 'false'
TRUST_X_FORWARDED_FOR = 'true'
TRUST_X_FORWARDED_PROTO = '{'true' if secure == 'true' else 'false'}'
SESSION_COOKIE_SECURE = '{secure}'
CSRF_COOKIE_SECURE = '{secure}'

DATABASES_DISABLE_SERVER_SIDE_CURSORS = '{'true' if cfg.pgbouncer else 'false'}'

WEB_CONCURRENCY = '{cfg.workers}'
DB_MAX_CONCURRENT_REQUESTS = '{db_max}'
# PostgreSQL 自动调参（由部署脚本按硬件写入，仅 local 模式应用）
PG_MAX_CONNECTIONS = '{cfg.db_max_connections}'
PG_SHARED_BUFFERS_MB = '{cfg.pg_shared_buffers_mb}'
PG_EFFECTIVE_CACHE_MB = '{cfg.pg_effective_cache_mb}'
PG_WORK_MEM_MB = '{cfg.pg_work_mem_mb}'
DB_BACKPRESSURE_TIMEOUT = '10'

CHANNEL_LAYER_BACKEND = 'postgres'
CHANNEL_POLL_INTERVAL = '0.1'
CACHE_DEFAULT_TIMEOUT = '300'
CACHE_TTL_CONTRACT_TYPES = '600'
CACHE_TTL_COMPANY_LIST = '15'
CACHE_TTL_BASEDATA = '20'
CACHE_TTL_INDUSTRY_FIELDS = '60'

LOGIN_FAIL_LIMIT = '10'
LOGIN_FAIL_WINDOW_SECONDS = '300'
LOGIN_LOCK_SECONDS = '900'
LOG_DIGEST_MAX_LENGTH = '2000'
NETWORK_LOG_RETENTION_DAYS = '30'
NETWORK_LOG_KEEP_ROWS = '200000'
BROADCAST_EVENT_RETENTION_DAYS = '7'
BROADCAST_EVENT_KEEP_ROWS = '100000'

UPLOAD_MAX_BYTES = '104857600'
MESSAGE_IMAGE_MAX_BYTES = '5242880'
UPLOAD_ALLOWED_EXTENSIONS = 'png,jpg,jpeg,gif,webp,pdf,xlsx,csv,zip,txt,md'
PACKAGE_MAX_BYTES = '104857600'
PACKAGE_MAX_FILES = '3000'
PACKAGE_MAX_UNCOMPRESSED_BYTES = '314572800'

CONTRACT_PAGE_SIZE = '50'
CONTRACT_PAGE_SIZE_MAX = '200'
CONTRACT_SYNC_LIMIT = '500'
CONTRACT_SYNC_LIMIT_MAX = '1000'
CONTRACT_TIMELINE_MAX = '300'
CONTRACT_CHECKS_MAX = '200'
CONTRACT_OVERDUE_HOURS = '24'
CONTRACT_FREEZE_TIMEOUT_HOURS = '24'
BASEDATA_PAGE_SIZE = '200'
BASEDATA_PAGE_SIZE_MAX = '500'
TIMER_MAX_DURATION_DAYS = '30'
"""


def write_env(runner: Runner, cfg: Config) -> None:
    UI.step('写入 .env')
    if cfg.mode == 'upgrade':
        UI.info('升级模式：保留现有 .env')
        return
    path = Path(cfg.app_dir) / '.env'
    if runner.dry_run:
        UI.info(f'[dry-run] 写入 {path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_env(cfg), encoding='utf-8')
    path.chmod(0o600)
    UI.ok(f'.env 已生成：{path}')


# ---------------------------------------------------------------- 系统依赖
def pkg_installed(name: str) -> bool:
    return subprocess.run(['dpkg', '-s', name], capture_output=True).returncode == 0


def install_system(runner: Runner, cfg: Config) -> None:
    UI.step('系统依赖')
    need = ['python3', 'python3-venv', 'python3-pip', 'rsync', 'curl', 'ca-certificates']
    if cfg.nginx_mode in ('system', 'manage') and not cfg.facts.system_nginx:
        need.append('nginx')
    if cfg.db_mode == 'local' and not cfg.facts.postgres_port:
        need += ['postgresql', 'postgresql-contrib']
    if cfg.pgbouncer:
        need.append('pgbouncer')
    if cfg.tls and not cfg.facts.certbot:
        need += ['certbot', 'python3-certbot-nginx']
    missing = [p for p in need if not (runner.dry_run or pkg_installed(p))]
    if runner.dry_run or missing:
        runner.run(['apt-get', 'update'])
        runner.run(['apt-get', 'install', '-y', '--no-install-recommends', *(missing or need)])
        UI.ok('系统依赖已安装')
    else:
        UI.ok('系统依赖已齐全，跳过 apt')


def ensure_user(runner: Runner, cfg: Config) -> None:
    UI.step('系统用户与目录')
    if runner.dry_run:
        UI.info(f'[dry-run] 创建用户 {SERVICE_USER} 与目录 {cfg.app_dir}')
        return
    try:
        import pwd
        exists = bool(pwd.getpwnam(SERVICE_USER))
    except KeyError:
        exists = False
    if not exists:
        runner.run(['useradd', '--system', '--home-dir', cfg.app_dir,
                    '--create-home', '--shell', '/usr/sbin/nologin', SERVICE_USER])
    Path(cfg.app_dir).mkdir(parents=True, exist_ok=True)
    UI.ok(f'目录：{cfg.app_dir}')


RSYNC_EXCLUDES = [
    '.git', '.venv', 'node_modules', '__pycache__', '.ruff_cache', '.gitignore',
    'BusinessCompetitionManagerWebFrontend/dist',
    'BusinessCompetitionManagerWebFrontend/node_modules',
    'BusinessCompetitionManagerWeb/media/uploads',
    'BusinessCompetitionManagerWeb/media/packages',
    'BusinessCompetitionManagerWeb/media/map_backgrounds',
    'BusinessCompetitionManagerWeb/media/messages',
    '/logs', '/reports', '/.env',
]


def sync_code(runner: Runner, cfg: Config) -> None:
    UI.step('同步代码')
    target = Path(cfg.app_dir)
    if target.resolve() == ROOT.resolve():
        UI.info('安装目录=源码目录，跳过同步')
        return
    cmd = ['rsync', '-a'] + [arg for pattern in RSYNC_EXCLUDES
                             for arg in ('--exclude', pattern)]
    cmd += [f'{ROOT}/', f'{cfg.app_dir}/']
    runner.run(cmd)
    if runner.dry_run:
        return
    required = ['BusinessCompetitionManagerWeb/manage.py',
                'BusinessCompetitionManagerWeb/apps/global_/logs/__init__.py']
    missing = [rel for rel in required if not (target / rel).exists()]
    if missing:
        die('代码同步不完整，缺少：' + '、'.join(missing))
    UI.ok('代码已同步（保留 .env / media 运行数据）')


def install_python(runner: Runner, cfg: Config) -> None:
    UI.step('后端依赖')
    app_dir = Path(cfg.app_dir)
    bootstrap = app_dir / '.bootstrap'
    runner.run(['python3', '-m', 'venv', str(bootstrap)])
    runner.run([str(bootstrap / 'bin' / 'pip'), 'install', '-q', '--upgrade', 'pip', 'uv'])
    uv = str(bootstrap / 'bin' / 'uv')
    uv_env = {'UV_PYTHON_INSTALL_DIR': UV_DIR}
    runner.run(['mkdir', '-p', UV_DIR])
    venv_python = app_dir / '.venv' / 'bin' / 'python'
    if not runner.dry_run and venv_python.exists():
        real = os.path.realpath(venv_python)
        if '/root/' in real:
            UI.warn('.venv 指向 /root 下的 Python（bcm 不可执行），重建')
            runner.run(['rm', '-rf', str(app_dir / '.venv')])
    runner.run([uv, 'python', 'install', '3.12'], env=uv_env)
    runner.run([uv, 'sync', '--frozen', '--python', '3.12', '--project', str(app_dir)],
               env=uv_env)
    runner.run(['chmod', '-R', 'a+rX', UV_DIR], check=False)
    # 插件运行时可能 import bcm_plugin_sdk 的构造函数，安装为可编辑包
    sdk_dir = app_dir / 'tools' / 'plugin-sdk'
    if sdk_dir.exists():
        runner.run([uv, 'pip', 'install', '--python', str(venv_python),
                    '-e', str(sdk_dir)], env=uv_env, check=False)
    if runner.dry_run:
        return
    if not venv_python.exists():
        die(f'虚拟环境创建失败：{venv_python}')
    check = runner.capture(['runuser', '-u', SERVICE_USER, '--', str(venv_python), '-V'])
    if check.returncode != 0:
        die(f'bcm 用户无法执行 {venv_python}：{check.stdout or check.stderr}')
    UI.ok(f'依赖就绪：{venv_python}')


# ---------------------------------------------------------------- 数据库
def apply_postgres_tuning(runner: Runner, cfg: Config) -> None:
    """仅 local 模式：按硬件写 ALTER SYSTEM；新装库会重启使内存参数生效。"""
    if not cfg.db_tune or cfg.db_mode != 'local':
        return
    if cfg.facts.postgres_port:
        UI.info('PostgreSQL 原本已在运行：跳过自动内存参数，避免影响同机其他库')
        return
    settings = {
        'max_connections': str(cfg.db_max_connections),
        'shared_buffers': f'{cfg.pg_shared_buffers_mb}MB',
        'effective_cache_size': f'{cfg.pg_effective_cache_mb}MB',
        'work_mem': f'{cfg.pg_work_mem_mb}MB',
        'maintenance_work_mem': f'{cfg.pg_maintenance_mem_mb}MB',
        'wal_buffers': f'{cfg.pg_wal_buffers_mb}MB',
        'random_page_cost': '1.1',
    }
    if runner.dry_run:
        UI.info('[dry-run] PostgreSQL 自动参数：'
                + '，'.join(f'{k}={v}' for k, v in settings.items()))
        return
    check = runner.capture(['sudo', '-u', 'postgres', 'psql', '-tAc', 'SELECT 1'])
    if check.returncode != 0:
        UI.warn('无法用 postgres 用户执行 ALTER SYSTEM，跳过 PostgreSQL 内存参数')
        return
    sql = '; '.join(
        f"ALTER SYSTEM SET {key} = '{value}'" for key, value in settings.items()) + ';'
    result = runner.run(
        ['sudo', '-u', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-c', sql],
        check=False)
    if result.returncode != 0:
        UI.warn('PostgreSQL 参数写入失败，保留原配置')
        return
    runner.run(['sudo', '-u', 'postgres', 'psql', '-c', 'SELECT pg_reload_conf()'],
               check=False)
    # 本次是新装/启动的 PostgreSQL，重启使 shared_buffers/max_connections 生效
    runner.run(['systemctl', 'restart', 'postgresql'], check=False)
    UI.ok('PostgreSQL 自动参数已写入并重启生效')


def setup_database(runner: Runner, cfg: Config) -> None:
    UI.step('数据库')
    if cfg.db_mode == 'existing':
        UI.info(f'使用已有库 {cfg.db_host}:{cfg.db_port}/{cfg.db_name}')
        return
    if cfg.facts.postgres_port:
        UI.info('检测到本机 PostgreSQL 已在运行，只创建库与账号')
        if not runner.dry_run:
            check = runner.capture(['sudo', '-u', 'postgres', 'psql', '-tAc', 'SELECT 1'])
            if check.returncode != 0:
                die('本机 5432 有 PostgreSQL，但无法用系统 postgres 用户管理它'
                    '（多为 1Panel/Docker）。请改用 --db-mode existing 并提供连接信息。')
    else:
        runner.run(['systemctl', 'enable', '--now', 'postgresql'])
    sql = (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{cfg.db_user}') THEN "
        f"CREATE ROLE {cfg.db_user} LOGIN PASSWORD '{cfg.db_password}'; "
        f"ELSE ALTER ROLE {cfg.db_user} WITH LOGIN PASSWORD '{cfg.db_password}'; END IF; "
        "END $$;"
    )
    runner.run(['sudo', '-u', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-c', sql])
    exists = runner.capture(
        ['sudo', '-u', 'postgres', 'psql', '-tAc',
         f"SELECT 1 FROM pg_database WHERE datname='{cfg.db_name}'"])
    if not runner.dry_run and (exists.stdout or '').strip() != '1':
        runner.run(['sudo', '-u', 'postgres', 'createdb', '-O', cfg.db_user, cfg.db_name])
    apply_postgres_tuning(runner, cfg)
    UI.ok('数据库就绪')


def set_env_db_endpoint(cfg: Config, host: str, port: str) -> None:
    path = Path(cfg.app_dir) / '.env'
    if not path.exists():
        return
    text = path.read_text(encoding='utf-8')
    text = re.sub(r'^DATABASES_HOST\s*=.*$', f"DATABASES_HOST = '{host}'", text, flags=re.M)
    text = re.sub(r'^DATABASES_PORT\s*=.*$', f"DATABASES_PORT = '{port}'", text, flags=re.M)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o600)


def _pgbouncer_backend(ini: Path) -> tuple[str, str]:
    """从现有 pgbouncer.ini 里读 * 的后端 host/port（没有则回退 127.0.0.1:5432）。"""
    try:
        text = ini.read_text(encoding='utf-8', errors='replace')
        match = re.search(r'^\*\s*=\s*host=(\S+)\s+port=(\S+)', text, re.M)
        if match:
            return match.group(1), match.group(2)
    except OSError:
        pass
    return '127.0.0.1', '5432'


def setup_pgbouncer(runner: Runner, cfg: Config) -> None:
    """安装/配置/校验 PgBouncer；校验失败自动回退直连，保证部署不中断。"""
    if not cfg.pgbouncer:
        return
    UI.step('PgBouncer')
    direct_host, direct_port = cfg.db_host, cfg.db_port
    if direct_port == '6432':
        # 已经切到 PgBouncer：从配置文件还原真实后端
        direct_host, direct_port = _pgbouncer_backend(Path('/etc/pgbouncer/pgbouncer.ini'))
    if direct_host in ('localhost', ''):
        direct_host = '127.0.0.1'

    if runner.dry_run:
        UI.info(f'[dry-run] 配置 PgBouncer：127.0.0.1:6432 → {direct_host}:{direct_port}')
        cfg.db_host, cfg.db_port = '127.0.0.1', '6432'
        return

    # 先确认直连 PostgreSQL 的账号密码是通的，否则 PgBouncer 必然失败
    direct_code = (
        "import os, sys, psycopg2\n"
        "try:\n"
        "    psycopg2.connect(dbname=os.environ['BCM_DB_NAME'], user=os.environ['BCM_DB_USER'],\n"
        "        password=os.environ['BCM_DB_PASSWORD'], host=os.environ['BCM_DB_HOST'],\n"
        "        port=os.environ['BCM_DB_PORT'], connect_timeout=5).close()\n"
        "except Exception as exc:\n"
        "    print(str(exc).strip()); sys.exit(1)\n"
    )
    direct = runner.capture(
        [str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'), '-c', direct_code],
        env={'BCM_DB_NAME': cfg.db_name, 'BCM_DB_USER': cfg.db_user,
             'BCM_DB_PASSWORD': cfg.db_password, 'BCM_DB_HOST': direct_host,
             'BCM_DB_PORT': direct_port},
    )
    if direct.returncode != 0:
        die(f'直连 PostgreSQL（{direct_host}:{direct_port}）认证失败：'
            f'{(direct.stdout or "").strip()}\n'
            '  说明 .env 里的 DATABASES_PASSWORD 与 PG 角色密码不一致，'
            '请先修正（ALTER ROLE 或改 .env），再重跑。')

    ini = Path('/etc/pgbouncer/pgbouncer.ini')
    userlist = Path('/etc/pgbouncer/userlist.txt')
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(f"""[databases]
* = host={direct_host} port={direct_port}

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = plain
auth_file = {userlist}
pool_mode = transaction
max_client_conn = {cfg.pgb_max_client}
default_pool_size = {cfg.pgb_pool_size}
min_pool_size = {max(2, cfg.pgb_pool_size // 6)}
reserve_pool_size = {cfg.pgb_reserve_pool}
server_reset_query = DISCARD ALL
ignore_startup_parameters = extra_float_digits,options
""", encoding='utf-8')
    escaped = cfg.db_password.replace('\\', '\\\\').replace('"', '\\"')
    userlist.write_text(f'"{cfg.db_user}" "{escaped}"\n', encoding='utf-8')
    userlist.chmod(0o600)
    try:
        import pwd
        pwd.getpwnam('pgbouncer')
        runner.run(['chown', 'pgbouncer:pgbouncer', str(ini), str(userlist)], check=False)
    except KeyError:
        pass

    # 关键：pgbouncer 已在运行时 `enable --now` 不会重新读取 userlist/ini，必须 restart
    runner.run(['systemctl', 'restart', 'pgbouncer'], check=False)
    runner.run(['systemctl', 'enable', 'pgbouncer'], check=False)
    for _ in range(10):
        if port_open('127.0.0.1', 6432):
            break
        time.sleep(0.5)

    if not port_open('127.0.0.1', 6432):
        UI.warn('PgBouncer 未监听 6432，回退为直连数据库')
        cfg.pgbouncer = False
        cfg.db_host, cfg.db_port = direct_host, direct_port
        set_env_db_endpoint(cfg, cfg.db_host, cfg.db_port)
        return

    # 用真实凭据经 6432 连一次，确认 userlist/后端认证都正确
    code = (
        "import os, sys, psycopg2\n"
        "try:\n"
        "    psycopg2.connect(dbname=os.environ['BCM_DB_NAME'], user=os.environ['BCM_DB_USER'],\n"
        "        password=os.environ['BCM_DB_PASSWORD'], host='127.0.0.1', port='6432',\n"
        "        connect_timeout=5).close()\n"
        "except Exception as exc:\n"
        "    print(str(exc).strip()); sys.exit(1)\n"
    )
    result = runner.capture(
        [str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'), '-c', code],
        env={'BCM_DB_NAME': cfg.db_name, 'BCM_DB_USER': cfg.db_user,
             'BCM_DB_PASSWORD': cfg.db_password},
    )
    if result.returncode != 0:
        logs = runner.capture(['journalctl', '-u', 'pgbouncer', '-n', '15', '--no-pager'])
        UI.warn('经 PgBouncer 连接失败：' + (result.stdout or '').strip())
        if (logs.stdout or '').strip():
            UI.warn('pgbouncer 日志：\n' + logs.stdout.strip())
        UI.warn(f'已回退为直连 {direct_host}:{direct_port}（.env 会写成 5432 或实际端口）')
        cfg.pgbouncer = False
        cfg.db_host, cfg.db_port = direct_host, direct_port
        set_env_db_endpoint(cfg, cfg.db_host, cfg.db_port)
        return

    cfg.db_host, cfg.db_port = '127.0.0.1', '6432'
    set_env_db_endpoint(cfg, '127.0.0.1', '6432')
    UI.ok('PgBouncer 已启动并校验通过：127.0.0.1:6432（transaction pooling）')



def db_env(cfg: Config) -> dict:
    return {
        'BCM_DB_NAME': cfg.db_name, 'BCM_DB_USER': cfg.db_user,
        'BCM_DB_PASSWORD': cfg.db_password, 'BCM_DB_HOST': cfg.db_host,
        'BCM_DB_PORT': cfg.db_port,
    }


def ensure_database(runner: Runner, cfg: Config) -> None:
    UI.step('确保数据库存在')
    if runner.dry_run:
        UI.info(f'[dry-run] 若 {cfg.db_name} 不存在则创建（owner={cfg.db_user}）')
        return
    code = (
        "import os, sys, psycopg2\n"
        "from psycopg2 import sql\n"
        "try:\n"
        "    conn = psycopg2.connect(dbname='postgres', user=os.environ['BCM_DB_USER'],\n"
        "        password=os.environ['BCM_DB_PASSWORD'], host=os.environ['BCM_DB_HOST'],\n"
        "        port=os.environ['BCM_DB_PORT'], connect_timeout=5)\n"
        "    conn.autocommit = True\n"
        "    cur = conn.cursor()\n"
        "    cur.execute('SELECT 1 FROM pg_database WHERE datname = %s',\n"
        "                (os.environ['BCM_DB_NAME'],))\n"
        "    if cur.fetchone():\n"
        "        print('EXISTS')\n"
        "    else:\n"
        "        cur.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(\n"
        "            sql.Identifier(os.environ['BCM_DB_NAME']),\n"
        "            sql.Identifier(os.environ['BCM_DB_USER'])))\n"
        "        print('CREATED')\n"
        "except Exception as exc:\n"
        "    print(str(exc).strip())\n"
        "    sys.exit(1)\n"
    )
    result = runner.capture([str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'), '-c', code],
                            env=db_env(cfg))
    detail = (result.stdout or '').strip()
    if result.returncode == 0:
        UI.ok('数据库已创建' if detail == 'CREATED' else '数据库已存在')
        return
    if 'permission denied' in detail.lower():
        die(f'数据库不存在且无权创建：{detail}\n'
            '  请在 1Panel 创建该库，或执行：ALTER ROLE <用户> CREATEDB;')
    die(f'数据库检查失败：{detail}')


def verify_database(runner: Runner, cfg: Config) -> None:
    UI.step('校验数据库连接')
    if runner.dry_run:
        return
    code = (
        "import os, sys, psycopg2\n"
        "try:\n"
        "    psycopg2.connect(dbname=os.environ['BCM_DB_NAME'], user=os.environ['BCM_DB_USER'],\n"
        "        password=os.environ['BCM_DB_PASSWORD'], host=os.environ['BCM_DB_HOST'],\n"
        "        port=os.environ['BCM_DB_PORT'], connect_timeout=5).close()\n"
        "except Exception as exc:\n"
        "    print(str(exc).strip()); sys.exit(1)\n"
    )
    result = runner.capture([str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'), '-c', code],
                            env=db_env(cfg))
    if result.returncode != 0:
        die(f'数据库连接失败：{(result.stdout or "").strip()}\n'
            f'  当前：{cfg.db_user}@{cfg.db_host}:{cfg.db_port}/{cfg.db_name}\n'
            '  1) 1Panel：重置该用户密码为 .env 中的值；\n'
            '  2) 系统 PG：sudo -u postgres psql -c "ALTER ROLE <用户> WITH PASSWORD \'<密码>\';"')
    UI.ok('数据库连接正常')


# ---------------------------------------------------------------- Django
def manage(runner: Runner, cfg: Config, *args, env=None, check=True):
    return runner.run(
        [str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'), 'manage.py', *args],
        cwd=Path(cfg.app_dir) / 'BusinessCompetitionManagerWeb', env=env, check=check,
    )


def migrate(runner: Runner, cfg: Config) -> None:
    UI.step('数据库迁移')
    manage(runner, cfg, 'migrate', '--noinput')
    UI.ok('迁移完成')


def ensure_admin(runner: Runner, cfg: Config) -> None:
    UI.step('管理员账号')
    if runner.dry_run:
        UI.info(f'[dry-run] 确保管理员 {cfg.admin_user} 存在')
        return
    env = {'DJANGO_SUPERUSER_PASSWORD': cfg.admin_password,
           'DJANGO_SUPERUSER_EMAIL': cfg.admin_email}
    manage(runner, cfg, 'createsuperuser', '--noinput', '--username', cfg.admin_user,
           env=env, check=False)
    code = ("from apps.global_.accounts.models import User\n"
            f"print(User.objects.filter(username={cfg.admin_user!r}, is_superuser=True).count())")
    result = runner.capture([str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'),
                             'manage.py', 'shell', '-c', code],
                            cwd=Path(cfg.app_dir) / 'BusinessCompetitionManagerWeb')
    if (result.stdout or '').strip().splitlines()[-1:] != ['1']:
        die(f'管理员 {cfg.admin_user} 创建失败，请手动执行：\n'
            f'  cd {Path(cfg.app_dir) / "BusinessCompetitionManagerWeb"} && '
            f'sudo -u {SERVICE_USER} ../../.venv/bin/python manage.py createsuperuser')
    if cfg.reset_admin:
        code = ("from apps.global_.accounts.models import User\n"
                f"u=User.objects.get(username={cfg.admin_user!r});"
                f"u.set_password({cfg.admin_password!r});u.is_active=True;u.save();"
                "print('RESET')")
        reset = runner.capture([str(Path(cfg.app_dir) / '.venv' / 'bin' / 'python'),
                                'manage.py', 'shell', '-c', code],
                               cwd=Path(cfg.app_dir) / 'BusinessCompetitionManagerWeb')
        if reset.returncode == 0:
            UI.ok('管理员密码已重置')
        else:
            UI.warn('管理员密码重置失败：' + (reset.stdout or '').strip())
    UI.ok(f'管理员 {cfg.admin_user} 可用')


# ---------------------------------------------------------------- 前端
def build_frontend(runner: Runner, cfg: Config) -> None:
    UI.step('前端')
    front = Path(cfg.app_dir) / 'BusinessCompetitionManagerWebFrontend'
    if cfg.build_frontend:
        if not shutil.which('npm') and not runner.dry_run:
            if cfg.yes or confirm('未安装 Node.js，安装 Node 20？', True):
                runner.run(['bash', '-c',
                            'curl -fsSL https://deb.nodesource.com/setup_20.x | bash -'])
                runner.run(['apt-get', 'install', '-y', 'nodejs'])
            else:
                die('缺少 Node.js，无法构建前端（可用 --no-frontend-build）')
        runner.run(['npm', 'ci'], cwd=front)
        runner.run(['npm', 'run', 'build'], cwd=front)
        UI.ok('前端已构建')
    else:
        UI.info('跳过构建（使用现有 dist）')

    if cfg.site_dir:
        target = Path(cfg.site_dir)
        if runner.dry_run:
            UI.info(f'[dry-run] 同步 dist → {target}')
        else:
            target.mkdir(parents=True, exist_ok=True)
            runner.run(['rsync', '-a', '--delete', f'{front}/dist/', f'{target}/'])
            try:
                import pwd
                pwd.getpwnam('www')
                runner.run(['chown', '-R', 'www:www', str(target)], check=False)
            except KeyError:
                pass
            UI.ok(f'前端已同步到站点目录：{target}')
    if not runner.dry_run and not (front / 'dist' / 'index.html').exists():
        UI.warn('未找到 dist/index.html，nginx 可能返回 404')


# ---------------------------------------------------------------- nginx
def write_nginx(runner: Runner, cfg: Config) -> None:
    UI.step('nginx')
    web_root = cfg.site_dir or f'{cfg.app_dir}/BusinessCompetitionManagerWebFrontend/dist'
    port = cfg.http_port if cfg.nginx_mode in ('system', 'manage') else 80
    if cfg.nginx_mode == 'system' and not runner.dry_run and port_open('127.0.0.1', port):
        if port == 80 and _openresty_running():
            if cfg.stop_openresty or (not cfg.yes and confirm(
                    '80 被 1Panel OpenResty 占用，停掉它并改用系统 nginx？', True)):
                runner.run(['systemctl', 'stop', 'openresty'], check=False)
                runner.run(['systemctl', 'disable', 'openresty'], check=False)
                time.sleep(1)
            else:
                cfg.http_port = 8080
                port = 8080
                UI.warn(f'80 被占用，改用 http://{cfg.domain}:{port}')
        else:
            cfg.http_port = 8080
            port = 8080
            UI.warn(f'80 被占用，改用 http://{cfg.domain}:{port}')

    conf = f"""upstream bcm_http {{
    server 127.0.0.1:{HTTP_PORT};
    keepalive 32;
}}
upstream bcm_ws {{
    server 127.0.0.1:{WS_PORT};
}}
map $http_upgrade $connection_upgrade {{
    default upgrade;
    ''      close;
}}
server {{
    listen {port}{' default_server' if cfg.nginx_mode == 'system' else ''};
    listen [::]:{port}{' default_server' if cfg.nginx_mode == 'system' else ''};
    server_name {cfg.domain} _;
    client_max_body_size 100m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy same-origin always;
    root {web_root};
    index index.html;
    location / {{
        try_files $uri $uri/ /index.html;
    }}
    location /assets/ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
        access_log off;
    }}
    location /api/ {{
        proxy_pass http://bcm_http;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_connect_timeout 5s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        proxy_request_buffering off;
    }}
    location /ws/ {{
        proxy_pass http://bcm_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        access_log off;
    }}
}}
"""
    export = Path(cfg.app_dir) / 'deploy' / 'nginx' / 'bcm.site.conf'
    if cfg.nginx_mode in ('manual', 'skip'):
        if runner.dry_run:
            UI.info(f'[dry-run] 生成站点配置 {export}（{cfg.nginx_mode}）')
            return
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(conf, encoding='utf-8')
        if cfg.nginx_mode == 'manual':
            UI.info(f'已导出站点配置：{export}（请在 1Panel 里替换站点配置或配反向代理）')
        return

    if runner.dry_run:
        UI.info(f'[dry-run] 写 nginx 配置（端口 {port}，root {web_root}）')
        return
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_text(conf, encoding='utf-8')
    conf_d = Path('/etc/nginx/conf.d')
    if conf_d.is_dir():
        (conf_d / 'bcm.conf').write_text(conf, encoding='utf-8')
    else:
        available = Path('/etc/nginx/sites-available/bcm.conf')
        enabled = Path('/etc/nginx/sites-enabled/bcm.conf')
        available.write_text(conf, encoding='utf-8')
        if enabled.exists() or enabled.is_symlink():
            enabled.unlink()
        enabled.symlink_to(available)
    if cfg.nginx_mode == 'system':
        default_site = Path('/etc/nginx/sites-enabled/default')
        if default_site.exists() or default_site.is_symlink():
            default_site.unlink()
    runner.run(['nginx', '-t'])
    runner.run(['systemctl', 'enable', '--now', 'nginx'])
    runner.run(['systemctl', 'reload', 'nginx'])
    UI.ok(f'nginx 已配置（端口 {port}）')


def service_state(name: str = SERVICE) -> str:
    try:
        out = subprocess.run(['systemctl', 'is-active', name],
                             capture_output=True, text=True)
        return (out.stdout or '').strip() or 'unknown'
    except OSError:
        return 'unavailable'


def _openresty_running() -> bool:
    for cmd in (['systemctl', 'is-active', '--quiet', 'openresty'],
                ['pgrep', '-f', 'openresty']):
        try:
            if subprocess.run(cmd, capture_output=True).returncode == 0:
                return True
        except OSError:
            pass
    return False


def _resolve_domain(domain: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(domain, 80, proto=socket.IPPROTO_TCP)
        return sorted({item[4][0] for item in infos})
    except OSError:
        return []


def _downgrade_env_to_http(runner: Runner, cfg: Config) -> None:
    """证书失败时把 .env 的安全项改回 HTTP，避免 Cookie Secure 导致登录失效。"""
    if runner.dry_run:
        return
    path = Path(cfg.app_dir) / '.env'
    if not path.exists():
        return
    text = path.read_text(encoding='utf-8')
    replacements = {
        'SECURE_SSL_REDIRECT': 'false',
        'SECURE_HSTS_SECONDS': '0',
        'TRUST_X_FORWARDED_PROTO': 'false',
        'SESSION_COOKIE_SECURE': 'false',
        'CSRF_COOKIE_SECURE': 'false',
    }
    for key, value in replacements.items():
        text = re.sub(rf'^{key}\s*=.*$', f"{key} = '{value}'", text, flags=re.M)
    path.write_text(text, encoding='utf-8')
    path.chmod(0o600)
    runner.run(['systemctl', 'restart', SERVICE], check=False)
    UI.warn('已回退为 HTTP 配置（.env 中的 Secure/HSTS 已关闭）')


def configure_tls(runner: Runner, cfg: Config) -> None:
    if not cfg.tls or cfg.ip_mode or cfg.nginx_mode in ('manual', 'skip'):
        return
    if cfg.http_port != 80:
        UI.warn(f'nginx 监听 {cfg.http_port}，certbot 的 HTTP 验证需要 80 端口，跳过证书')
        return

    UI.step('HTTPS 证书（自动申请）')
    if runner.dry_run:
        UI.info(f'[dry-run] certbot --nginx -d {cfg.domain}（含自动续期 timer）')
        return

    resolved = _resolve_domain(cfg.domain)
    if not resolved:
        UI.warn(f'域名 {cfg.domain} 当前无法解析，跳过证书申请（站点仍走 HTTP）')
        _downgrade_env_to_http(runner, cfg)
        return
    if cfg.facts.local_ip and cfg.facts.local_ip not in resolved and not cfg.force_cert:
        UI.warn(f'域名解析到 {", ".join(resolved)}，本机 IP 是 {cfg.facts.local_ip}；'
                '如确认解析无误可加 --force-cert 仍尝试申请')

    result = runner.run(
        ['certbot', '--nginx', '-d', cfg.domain, '--non-interactive', '--agree-tos',
         '-m', cfg.admin_email, '--redirect', '--keep-until-expiring',
         '--deploy-hook', f'systemctl reload {SERVICE}'],
        check=False,
    )
    if result.returncode != 0:
        UI.warn('certbot 申请失败（常见：DNS 未解析到本机、80 端口不通、'
                '域名已被其他站点占用）。站点仍可用 HTTP。')
        _downgrade_env_to_http(runner, cfg)
        return

    # 自动续期：certbot 包自带 timer；确保开启
    runner.run(['systemctl', 'enable', '--now', 'certbot.timer'], check=False)

    # 验证 443 握手（不校验证书，避免 NAT 回环问题）
    try:
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection(('127.0.0.1', 443), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=cfg.domain):
                pass
        UI.ok(f'HTTPS 已启用：https://{cfg.domain}（证书自动续期已开启）')
    except OSError as exc:
        UI.warn(f'证书已申请，但 443 握手检查失败：{exc}（可稍后 nginx -t 检查）')



def setup_firewall(runner: Runner, cfg: Config) -> None:
    if not cfg.firewall:
        return
    UI.step('防火墙')
    if not shutil.which('ufw'):
        runner.run(['apt-get', 'install', '-y', 'ufw'])
    runner.run(['ufw', 'allow', 'OpenSSH'])
    runner.run(['ufw', 'allow', 'Nginx Full'])
    if cfg.http_port != 80:
        runner.run(['ufw', 'allow', f'{cfg.http_port}/tcp'])
    runner.run(['ufw', '--force', 'enable'])
    UI.ok('ufw 已启用')


# ---------------------------------------------------------------- systemd
def write_service(runner: Runner, cfg: Config) -> None:
    UI.step('systemd 服务')
    unit = f"""[Unit]
Description=BCM backend (waitress :{HTTP_PORT} + daphne :{WS_PORT})
After=network.target postgresql.service
Wants=network.target

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
WorkingDirectory={cfg.app_dir}
ExecStart={cfg.app_dir}/.venv/bin/python scripts/run_servers.py --workers {cfg.workers} --threads {cfg.threads} --no-reload --host 127.0.0.1
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
    path = Path(f'/etc/systemd/system/{SERVICE}.service')
    if runner.dry_run:
        UI.info(f'[dry-run] 写入 {path}')
        return
    path.write_text(unit, encoding='utf-8')
    runner.run(['systemctl', 'daemon-reload'])
    runner.run(['systemctl', 'enable', '--now', SERVICE])
    UI.ok(f'{SERVICE}.service 已启动')


def fix_permissions(runner: Runner, cfg: Config) -> None:
    if runner.dry_run:
        return
    runner.run(['chown', '-R', f'{SERVICE_USER}:{SERVICE_USER}', cfg.app_dir])
    UI.ok('目录权限已交给 ' + SERVICE_USER)


def health(runner: Runner, cfg: Config) -> None:
    UI.step('健康检查')
    if runner.dry_run:
        return
    import urllib.request
    for _ in range(30):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{HTTP_PORT}/api/health',
                                        timeout=3) as resp:
                if resp.status == 200:
                    UI.ok('后端健康检查通过')
                    return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    UI.warn('后端 30 秒内未就绪：journalctl -u bcm -n 100 --no-pager')


# ---------------------------------------------------------------- 模式
def run_install(runner: Runner, cfg: Config) -> None:
    install_system(runner, cfg)
    setup_database(runner, cfg)
    ensure_user(runner, cfg)
    sync_code(runner, cfg)
    install_python(runner, cfg)
    setup_pgbouncer(runner, cfg)
    write_env(runner, cfg)
    ensure_database(runner, cfg)
    verify_database(runner, cfg)
    migrate(runner, cfg)
    ensure_admin(runner, cfg)
    build_frontend(runner, cfg)
    fix_permissions(runner, cfg)
    write_service(runner, cfg)
    write_nginx(runner, cfg)
    configure_tls(runner, cfg)
    setup_firewall(runner, cfg)
    health(runner, cfg)


def run_upgrade(runner: Runner, cfg: Config) -> None:
    sync_code(runner, cfg)
    install_python(runner, cfg)
    setup_pgbouncer(runner, cfg)
    verify_database(runner, cfg)
    migrate(runner, cfg)
    build_frontend(runner, cfg)
    fix_permissions(runner, cfg)
    runner.run(['systemctl', 'restart', SERVICE])
    health(runner, cfg)


def run_doctor(cfg: Config) -> int:
    UI.step('环境体检')
    facts = cfg.facts
    problems = 0

    def check(label: str, condition: bool, detail: str = '') -> None:
        nonlocal problems
        if condition:
            UI.ok(f'{label}{("：" + detail) if detail else ""}')
        else:
            problems += 1
            UI.fail(f'{label}{("：" + detail) if detail else ""}')

    check('Debian 系统', facts.debian)
    check('root 权限', facts.root)
    check('磁盘 ≥2GB', facts.disk_free_gb >= 2, f'{facts.disk_free_gb:.1f}GB')
    env_path = Path(cfg.app_dir) / '.env'
    check('.env 存在', env_path.exists(), str(env_path))
    if env_path.exists():
        env = read_env(env_path)
        for key in ('SECRET_KEY', 'DATABASES_NAME', 'DATABASES_PASSWORD'):
            check(f'.env 含 {key}', bool(env.get(key)))
    active = service_state() == 'active'
    check(f'{SERVICE}.service 运行中', active)
    if active:
        try:
            import urllib.request
            with urllib.request.urlopen(f'http://127.0.0.1:{HTTP_PORT}/api/health',
                                        timeout=3) as resp:
                check('/api/health', resp.status == 200)
        except Exception as exc:  # noqa: BLE001
            check('/api/health', False, str(exc))
    check('8000 监听', port_open('127.0.0.1', HTTP_PORT))
    check('8001 监听', port_open('127.0.0.1', WS_PORT))
    env_data = read_env(env_path) if env_path.exists() else {}
    if env_data.get('DATABASES_PORT') == '6432':
        check('PgBouncer 6432 监听', port_open('127.0.0.1', 6432))
        check('pgbouncer 服务运行', service_state('pgbouncer') == 'active')
    if env_data.get('SECURE_SSL_REDIRECT') == 'true':
        check('443 监听（HTTPS 已启用）', port_open('127.0.0.1', 443))
    if facts.system_nginx:
        conf = Path('/etc/nginx/conf.d/bcm.conf')
        check('nginx 站点配置', conf.exists(), str(conf))
    else:
        UI.warn('未检测到系统 nginx（1Panel/OpenResty 场景请确认站点已配置）')
    print()
    if problems:
        UI.warn(f'发现 {problems} 个问题，按上面提示修复后可重跑 doctor')
        return 1
    UI.ok('体检通过')
    return 0


def run_status(cfg: Config) -> int:
    env_path = Path(cfg.app_dir) / '.env'
    env = read_env(env_path)
    active = service_state()
    try:
        import urllib.request
        with urllib.request.urlopen(f'http://127.0.0.1:{HTTP_PORT}/api/health',
                                    timeout=3) as resp:
            healthy = resp.status
    except Exception:  # noqa: BLE001
        healthy = '不可用'
    proto = 'https' if env.get('SECURE_SSL_REDIRECT') == 'true' else 'http'
    print(f'安装目录：{cfg.app_dir}')
    print(f'服务状态：{active or "未知"}　健康检查：{healthy}')
    print(f'数据库：{env.get("DATABASES_USER")}@{env.get("DATABASES_HOST")}:'
          f'{env.get("DATABASES_PORT")}/{env.get("DATABASES_NAME")}')
    print(f'自动参数：max_connections={env.get("PG_MAX_CONNECTIONS", "?")} '
          f'shared_buffers={env.get("PG_SHARED_BUFFERS_MB", "?")}MB '
          f'DB_MAX_CONCURRENT_REQUESTS={env.get("DB_MAX_CONCURRENT_REQUESTS", "?")}')
    print(f'访问地址：{proto}://{env.get("ALLOWED_HOSTS", "?")}')
    print(f'站点目录：{env.get("SITE_DIR", "（未配置，使用默认 dist）")}')
    print('常用命令：systemctl status|restart bcm；journalctl -u bcm -n 100 --no-pager')
    return 0


def print_summary(cfg: Config) -> None:
    UI.step('部署完成')
    secure = cfg.tls and not cfg.ip_mode
    proto = 'https' if secure else 'http'
    suffix = '' if cfg.http_port == 80 or secure else f':{cfg.http_port}'
    lines = [
        f'站点：        {proto}://{cfg.domain}{suffix}',
        f'安装目录：    {cfg.app_dir}',
        f'后端端口：    127.0.0.1:{HTTP_PORT}（HTTP）/ {WS_PORT}（WS）',
        f'管理员账号：  {cfg.admin_user}',
        f'管理员密码：  {cfg.admin_password}（仅首次创建/重置时有效）',
        f'数据库：      {cfg.db_name}（用户 {cfg.db_user}）',
        f'自动参数：    {cfg.workers} worker × {cfg.threads} 线程，'
        f'max_connections {cfg.db_max_connections}，'
        f'shared_buffers {cfg.pg_shared_buffers_mb}MB，'
        f'PgBouncer 池 {cfg.pgb_pool_size}',
        '',
        '常用命令：',
        f'  systemctl status {SERVICE}',
        f'  systemctl restart {SERVICE}',
        f'  journalctl -u {SERVICE} -n 100 --no-pager',
        '  tail -f /var/log/nginx/access.log',
        '',
        f'配置文件：{cfg.app_dir}/.env（改后 systemctl restart {SERVICE}）',
    ]
    text = '\n'.join(lines)
    print('\n' + text)
    if not cfg.dry_run:
        path = Path(cfg.app_dir) / 'DEPLOY_SUMMARY.txt'
        path.write_text(text + '\n', encoding='utf-8')
        path.chmod(0o600)
        UI.info(f'摘要已保存：{path}')


# ---------------------------------------------------------------- 入口
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='BCM Debian 部署/运维脚本（install / upgrade / doctor / status）')
    parser.add_argument('mode', nargs='?', default='install',
                        choices=['install', 'upgrade', 'doctor', 'status'])
    parser.add_argument('--domain', help='站点域名（也可直接填 IP）')
    parser.add_argument('--ip', help='纯 IP 部署地址（等价于 --domain 传 IP）')
    parser.add_argument('--app-dir', help='安装目录（默认 /opt/bcm）')
    parser.add_argument('--site-dir', help='把前端 dist 同步到该目录（1Panel 站点根目录）')
    parser.add_argument('--admin-user', help='管理员用户名')
    parser.add_argument('--admin-email', help='管理员邮箱')
    parser.add_argument('--admin-password', help='管理员密码（不填自动生成）')
    parser.add_argument('--reset-admin-password', action='store_true',
                        help='管理员已存在时重置密码为本次密码')
    parser.add_argument('--db-mode', choices=['auto', 'local', 'existing'], help='数据库模式')
    parser.add_argument('--db-name', help='数据库名')
    parser.add_argument('--db-user', help='数据库用户')
    parser.add_argument('--db-password', help='数据库密码')
    parser.add_argument('--db-host', help='数据库主机')
    parser.add_argument('--db-port', help='数据库端口')
    parser.add_argument('--workers', type=int, help='HTTP worker 数')
    parser.add_argument('--threads', type=int, help='每个 worker 的线程数')
    parser.add_argument('--http-port', type=int, help='nginx 监听端口（默认 80）')
    parser.add_argument('--nginx-mode', choices=['auto', 'system', 'manage', 'manual'],
                        help='nginx 模式（默认自动判断）')
    parser.add_argument('--stop-openresty', action='store_true',
                        help='80 被 1Panel OpenResty 占用时停掉它')
    parser.add_argument('--force-cert', action='store_true',
                        help='域名解析与本机 IP 不一致时仍尝试申请证书')
    tls_group = parser.add_mutually_exclusive_group()
    tls_group.add_argument('--tls', dest='tls', action='store_true', default=None)
    tls_group.add_argument('--no-tls', dest='tls', action='store_false')
    parser.add_argument('--no-frontend-build', dest='build_frontend', action='store_false',
                        default=None, help='不构建前端（使用现有 dist）')
    pgb_group = parser.add_mutually_exclusive_group()
    pgb_group.add_argument('--pgbouncer', dest='pgbouncer', action='store_true', default=True,
                           help='部署时启动 PgBouncer（默认开启）')
    pgb_group.add_argument('--no-pgbouncer', dest='pgbouncer', action='store_false')
    db_tune_group = parser.add_mutually_exclusive_group()
    db_tune_group.add_argument('--db-tune', dest='no_db_tune', action='store_false',
                               default=False, help='按硬件自动写 PostgreSQL 参数（默认开启）')
    db_tune_group.add_argument('--no-db-tune', dest='no_db_tune', action='store_true',
                               help='不改 PostgreSQL 参数')
    fw_group = parser.add_mutually_exclusive_group()
    fw_group.add_argument('--firewall', dest='firewall', action='store_true', default=None)
    fw_group.add_argument('--no-firewall', dest='firewall', action='store_false')
    parser.add_argument('--yes', action='store_true', help='全部使用默认值/自动生成')
    parser.add_argument('--dry-run', action='store_true', help='只打印计划，不执行')
    parser.add_argument('--verbose', action='store_true', help='打印每条命令')
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    facts = detect()
    env_path = Path(args.app_dir or '/opt/bcm') / '.env'

    if args.mode == 'doctor':
        cfg = Config(app_dir=str(Path(args.app_dir or '/opt/bcm').resolve()), facts=facts)
        return run_doctor(cfg)
    if args.mode == 'status':
        cfg = Config(app_dir=str(Path(args.app_dir or '/opt/bcm').resolve()), facts=facts)
        return run_status(cfg)

    if args.dry_run:
        UI.warn('dry-run：只打印计划，不修改系统')
    UI.step('环境探测')
    show_facts(facts)

    try:
        cfg = collect(args, facts, env_path)
        preflight(cfg)
        if not cfg.dry_run and not cfg.yes:
            print()
            UI.info(f'模式：{cfg.mode}　地址：{cfg.domain}　目录：{cfg.app_dir}　'
                    f'nginx：{cfg.nginx_mode}　HTTPS：{"是" if cfg.tls else "否"}')
            if not confirm('确认开始？', True):
                return 0
        runner = Runner(cfg.dry_run, cfg.verbose)
        if cfg.mode == 'upgrade':
            run_upgrade(runner, cfg)
        else:
            run_install(runner, cfg)
            print_summary(cfg)
        return 0
    except Abort:
        return 1
    except KeyboardInterrupt:
        print('\n已中断')
        return 130


if __name__ == '__main__':
    sys.exit(main())
