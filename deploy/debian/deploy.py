#!/usr/bin/env python3
"""Debian 一键部署脚本（Python 3.8+，Debian 自带 python3 即可运行）。

用法（在仓库根目录执行）：
    sudo python3 deploy/debian/deploy.py
    sudo python3 deploy/debian/deploy.py --domain bcm.example.com --yes

规则：
- **能自动生成的直接生成**：SECRET_KEY、数据库密码、管理员初始密码（生成后展示一次）；
- **不能猜的才询问**：域名、是否装本地 PostgreSQL、是否签发 HTTPS 证书、是否构建前端；
- 其余走默认值（安装目录 /opt/bcm、worker=CPU 核数、线程 8 等），回车即接受；
- `--dry-run` 只打印计划不执行（可在任意系统上预演）。
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_NAME_DEFAULT = 'business_competition_manager'
DB_USER_DEFAULT = 'bcm_app'
SERVICE_USER = 'bcm'
SERVICE_NAME = 'bcm'
BACKEND_PORT = 8000
WS_PORT = 8001


# ---------------------------------------------------------------- 输出
class C:
    OK = '\033[32m'
    WARN = '\033[33m'
    ERR = '\033[31m'
    INFO = '\033[36m'
    BOLD = '\033[1m'
    END = '\033[0m'


def _color_enabled() -> bool:
    return sys.stdout.isatty() and os.environ.get('NO_COLOR') is None


def info(msg: str) -> None:
    print(f'{C.INFO}[信息]{C.END} {msg}' if _color_enabled() else f'[信息] {msg}')


def ok(msg: str) -> None:
    print(f'{C.OK}[完成]{C.END} {msg}' if _color_enabled() else f'[完成] {msg}')


def warn(msg: str) -> None:
    print(f'{C.WARN}[注意]{C.END} {msg}' if _color_enabled() else f'[注意] {msg}')


def step(title: str) -> None:
    line = f'== {title} ' + '=' * max(0, 60 - len(title))
    print(f'\n{C.BOLD}{line}{C.END}' if _color_enabled() else f'\n{line}')


def die(msg: str) -> None:
    print(f'{C.ERR}[失败]{C.END} {msg}' if _color_enabled() else f'[失败] {msg}')
    sys.exit(1)


# ---------------------------------------------------------------- 交互
def ask(question: str, default: str = '', *, required: bool = False,
        secret_input: bool = False) -> str:
    hint = f'（默认：{default}）' if default else ''
    while True:
        if secret_input:
            value = getpass.getpass(f'{question}{hint}：')
        else:
            value = input(f'{question}{hint}：').strip()
        if value:
            return value
        if default:
            return default
        if not required:
            return ''
        print('  该项不能为空，请重新输入。')


def confirm(question: str, default: bool = True) -> bool:
    suffix = '[Y/n]' if default else '[y/N]'
    value = input(f'{question} {suffix}：').strip().lower()
    if not value:
        return default
    return value in ('y', 'yes', '是')


def detect_primary_ip() -> str:
    """尽力探测本机对外 IP（供纯 IP 部署做默认值；失败返回空串）。"""
    import socket
    import subprocess

    try:
        result = subprocess.run(['ip', '-4', 'route', 'get', '1.1.1.1'],
                                capture_output=True, text=True, timeout=3)
        parts = result.stdout.split()
        if 'src' in parts:
            candidate = parts[parts.index('src') + 1]
            if candidate and not candidate.startswith('127.'):
                return candidate
    except Exception:  # noqa: BLE001
        pass

    try:
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True,
                                timeout=3)
        for candidate in result.stdout.split():
            if candidate and not candidate.startswith('127.'):
                return candidate
    except Exception:  # noqa: BLE001
        pass

    try:
        candidate = socket.gethostbyname(socket.gethostname())
        if candidate and not candidate.startswith('127.'):
            return candidate
    except OSError:
        pass
    return ''


def _is_ip(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def gen_token(length: int = 48) -> str:
    return secrets.token_urlsafe(length)


# ---------------------------------------------------------------- 执行
class Runner:
    def __init__(self, dry_run: bool):
        self.dry_run = dry_run

    def run(self, cmd, *, cwd: Path | None = None, env: dict | None = None,
            check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
        printable = ' '.join(str(part) for part in cmd)
        if self.dry_run:
            info(f'[dry-run] {printable}')
            return subprocess.CompletedProcess(cmd, 0, b'', b'')
        info(printable)
        return subprocess.run(
            [str(part) for part in cmd], cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})}, check=check,
            capture_output=capture, text=bool(capture),
        )

    def shell(self, script: str, *, check: bool = True) -> subprocess.CompletedProcess:
        if self.dry_run:
            info(f'[dry-run] bash -c <<< {script[:120]}...')
            return subprocess.CompletedProcess(['bash', '-c', script], 0, b'', b'')
        return subprocess.run(['bash', '-c', script], check=check)


# ---------------------------------------------------------------- 系统检测
def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect_system(assume: list[str]) -> dict:
    """检测已安装的组件（1Panel 装过的就不要重复安装）。"""
    facts = {
        'onepanel': Path('/opt/1panel').exists() or bool(shutil.which('1pctl')),
        'nginx': bool(shutil.which('nginx')) or Path('/usr/sbin/nginx').exists(),
        'openresty': bool(shutil.which('openresty')),
        'psql': bool(shutil.which('psql')),
        'postgres_port': port_open('127.0.0.1', 5432),
        'node': bool(shutil.which('node')),
        'certbot': bool(shutil.which('certbot')),
        'python_venv': True,
    }
    for name in assume:
        if name in ('nginx', 'openresty'):
            facts['nginx'] = True
        elif name in ('postgres', 'pg'):
            facts['postgres_port'] = True
            facts['psql'] = True
        elif name == 'onepanel':
            facts['onepanel'] = True
        elif name == 'node':
            facts['node'] = True
        elif name == 'certbot':
            facts['certbot'] = True
    facts['nginx'] = facts['nginx'] or facts['openresty']
    return facts


def print_detection(facts: dict) -> None:
    info('系统检测结果：')
    rows = [
        ('1Panel', facts['onepanel']),
        ('Nginx / OpenResty', facts['nginx']),
        ('PostgreSQL（5432 端口在监听）', facts['postgres_port']),
        ('psql 客户端', facts['psql']),
        ('Node.js', facts['node']),
        ('certbot', facts['certbot']),
    ]
    for label, value in rows:
        print(f'  {"✓ 已存在" if value else "✗ 未检测到"}  {label}')


# ---------------------------------------------------------------- 配置
@dataclass
class Config:
    domain: str = ''            # 域名或 IP（纯 IP 部署时就是 IP）
    ip_mode: bool = False       # 纯 IP：不做 HTTPS 证书
    app_dir: str = '/opt/bcm'
    admin_user: str = 'admin'
    admin_email: str = ''
    admin_password: str = ''
    db_mode: str = 'local'          # local | existing
    db_name: str = DB_NAME_DEFAULT
    db_user: str = DB_USER_DEFAULT
    db_password: str = ''
    db_host: str = 'localhost'
    db_port: str = '5432'
    workers: int = 4
    threads: int = 8
    tls: bool = True
    build_frontend: bool = True
    firewall: bool = True
    nginx_mode: str = 'manage'      # manage=脚本写配置 | manual=用户自己在 1Panel 配
    facts: dict = field(default_factory=dict)
    pg_detected: bool = False
    nginx_detected: bool = False
    onepanel: bool = False
    secret_key: str = ''
    assume_yes: bool = False
    dry_run: bool = False
    notes: list = field(default_factory=list)


def collect(cli) -> Config:
    cfg = Config(dry_run=cli.dry_run, assume_yes=cli.yes)

    step('基础信息')
    detected_ip = detect_primary_ip()
    if cli.ip:
        cfg.domain = cli.ip
        cfg.ip_mode = True
        if cli.domain:
            die('--ip 与 --domain 只能二选一')
    elif cli.domain:
        cfg.domain = cli.domain
        cfg.ip_mode = _is_ip(cli.domain)
    elif cli.yes:
        if not detected_ip:
            die('--yes 模式需要 --domain 或 --ip（未能自动检测本机 IP）')
        cfg.domain = detected_ip
        cfg.ip_mode = True
        warn(f'未指定域名/IP，自动使用本机检测到的 IP：{detected_ip}'
             '（公网 IP 不同请用 --ip 指定）')
    else:
        cfg.domain = ask('站点域名或公网 IP（如 bcm.example.com / 203.0.113.10）',
                         detected_ip, required=True)
        cfg.ip_mode = _is_ip(cfg.domain)

    if cfg.ip_mode:
        cfg.tls = False
        info(f'纯 IP 部署：{cfg.domain}（HTTP，不做 HTTPS 证书）')
        info('提示：纯 IP 走 HTTP 时密码/令牌是明文传输，公网使用建议套 VPN/SSH 隧道，'
             '或改用域名后开启 HTTPS。')

    cfg.app_dir = cli.app_dir or (ask('安装目录', '/opt/bcm') if not cli.yes else '/opt/bcm')
    cfg.admin_user = cli.admin_user or (ask('管理员用户名', 'admin') if not cli.yes else 'admin')
    # 纯 IP 的 admin@203.0.113.10 过不了邮箱校验，默认用 example.com 占位
    default_email = 'admin@example.com' if cfg.ip_mode else f'admin@{cfg.domain}'
    cfg.admin_email = cli.admin_email or (
        ask('管理员邮箱', default_email) if not cli.yes else default_email)

    generated = gen_token(12)
    if cli.yes:
        cfg.admin_password = generated
        info('管理员初始密码已自动生成')
    else:
        if confirm('管理员初始密码自动生成？', True):
            cfg.admin_password = generated
        else:
            cfg.admin_password = ask('管理员密码', required=True, secret_input=True)

    step('系统检测')
    facts = detect_system(cli.assume_detected or [])
    cfg.facts = facts
    cfg.onepanel = facts['onepanel']
    cfg.pg_detected = facts['postgres_port']
    cfg.nginx_detected = facts['nginx']
    print_detection(facts)
    if facts['onepanel']:
        info('检测到 1Panel：已通过 1Panel 安装的 PostgreSQL / Nginx 不会重复安装。')

    step('数据库')
    if cli.db_mode:
        cfg.db_mode = cli.db_mode
    elif facts['postgres_port']:
        # 已在监听 5432（多半是 1Panel 装的）：默认复用，不再安装
        if cli.yes:
            cfg.db_mode = 'existing'
        else:
            cfg.db_mode = 'existing' if confirm(
                '检测到本机 PostgreSQL 已在运行（可能是 1Panel 安装），直接使用它？', True) else 'local'
    elif not cli.yes:
        mode = ask('数据库模式：local=本机安装 PostgreSQL / existing=使用已有数据库', 'local')
        cfg.db_mode = mode if mode in ('local', 'existing') else 'local'
    if cfg.db_mode == 'existing':
        info('提示：数据库与账号请在 1Panel「数据库」里创建，然后把连接信息填到下面。')
    if cfg.db_mode == 'existing':
        if cli.yes:
            cfg.db_host = cli.db_host or 'localhost'
            cfg.db_port = cli.db_port or '5432'
            cfg.db_name = cli.db_name or DB_NAME_DEFAULT
            cfg.db_user = cli.db_user or DB_USER_DEFAULT
            cfg.db_password = cli.db_password or ''
        else:
            cfg.db_host = cli.db_host or ask('数据库主机', 'localhost')
            cfg.db_port = cli.db_port or ask('数据库端口', '5432')
            cfg.db_name = cli.db_name or ask('数据库名', DB_NAME_DEFAULT)
            cfg.db_user = cli.db_user or ask('数据库用户', DB_USER_DEFAULT)
            cfg.db_password = cli.db_password or ask(
                '数据库密码', required=True, secret_input=True)
        if not cfg.db_password:
            die('existing 模式必须提供数据库密码（--db-password 或交互输入）')
    else:
        cfg.db_name = cli.db_name or (
            ask('将创建的数据库名', DB_NAME_DEFAULT) if not cli.yes else DB_NAME_DEFAULT)
        cfg.db_user = cli.db_user or (
            ask('将创建的数据库用户', DB_USER_DEFAULT) if not cli.yes else DB_USER_DEFAULT)
        cfg.db_password = cli.db_password or gen_token(24)

    cpu = os.cpu_count() or 2
    cfg.workers = int(cli.workers or (ask('HTTP worker 进程数', str(cpu)) if not cli.yes else cpu))
    cfg.threads = int(cli.threads or (ask('每个 worker 的线程数', '8') if not cli.yes else 8))

    step('部署选项')
    if cfg.ip_mode:
        cfg.tls = False
    else:
        cfg.tls = cli.tls if cli.tls is not None else (
            True if cli.yes else confirm(
                '为域名申请 HTTPS 证书（Let\'s Encrypt，需 DNS 已解析到本机）？', True))
    cfg.build_frontend = cli.build_frontend if cli.build_frontend is not None else (
        True if cli.yes else confirm('在本机构建前端（需要 Node.js 20+）？', True))
    if cli.nginx_mode:
        cfg.nginx_mode = cli.nginx_mode
    elif facts['nginx'] and not cli.yes:
        mode = ask(
            '检测到 Nginx：manage=由脚本写配置 / manual=跳过，稍后在 1Panel 里配置', 'manual')
        cfg.nginx_mode = mode if mode in ('manage', 'manual') else 'manual'
    elif facts['nginx'] and cli.yes:
        cfg.nginx_mode = 'manual'

    if cfg.nginx_mode == 'manual':
        cfg.tls = False
        info('manual 模式：HTTPS 证书请直接在 1Panel 网站里申请。')

    if cli.firewall is not None:
        cfg.firewall = cli.firewall
    elif facts['onepanel']:
        cfg.firewall = False
        info('检测到 1Panel：防火墙交给 1Panel 管理，跳过 ufw。')
    else:
        cfg.firewall = True if cli.yes else confirm(
            '启用 ufw 防火墙（放行 SSH/80/443）？', True)

    cfg.secret_key = gen_token(48)
    return cfg


# ---------------------------------------------------------------- 系统检查
def preflight(cfg: Config) -> None:
    if cfg.dry_run:
        return
    if platform.system() != 'Linux':
        die('该脚本只能在 Debian Linux 上执行（本机可用 --dry-run 预演）')
    if os.geteuid() != 0:
        die('请用 root 执行：sudo python3 deploy/debian/deploy.py')
    os_release = Path('/etc/os-release').read_text(encoding='utf-8', errors='replace')
    if 'ID=debian' not in os_release and 'ID_LIKE=debian' not in os_release:
        warn('当前系统不是 Debian 系，继续执行可能失败')


# ---------------------------------------------------------------- 各步骤
def _pkg_installed(name: str) -> bool:
    return subprocess.run(['dpkg', '-s', name], capture_output=True).returncode == 0


def install_packages(runner: Runner, cfg: Config, facts: dict) -> None:
    step('安装系统依赖（已存在的跳过）')
    if runner.dry_run:
        info('[dry-run] 检测结果：'
             f'nginx={facts["nginx"]} postgres={facts["postgres_port"]} '
             f'1panel={facts["onepanel"]}')
        info('[dry-run] 只安装缺失的系统包（已存在的不动）')
        return
    packages = ['python3', 'python3-venv', 'python3-pip', 'rsync', 'curl', 'ca-certificates']
    if not facts['nginx']:
        packages.append('nginx')
    else:
        info('Nginx 已存在，跳过安装（1Panel 管理的保持不动）')
    if cfg.db_mode == 'local' and not facts['postgres_port']:
        packages += ['postgresql', 'postgresql-contrib']
    else:
        info('PostgreSQL 已存在或使用已有库，跳过安装')
    if cfg.tls:
        if facts['certbot']:
            info('certbot 已存在，跳过安装')
        else:
            packages += ['certbot', 'python3-certbot-nginx']

    missing = [name for name in packages if not _pkg_installed(name)]
    if not missing:
        info('所需系统包均已安装，跳过 apt')
        return
    runner.run(['apt-get', 'update'])
    runner.run(['apt-get', 'install', '-y', '--no-install-recommends', *missing])
    ok(f'已安装：{" ".join(missing)}')


def setup_database(runner: Runner, cfg: Config) -> None:
    step('数据库')
    if cfg.db_mode == 'existing':
        info(f'使用已有数据库 {cfg.db_host}:{cfg.db_port}/{cfg.db_name}，跳过安装与创建')
        return
    if cfg.pg_detected:
        # 已有实例（1Panel 装的通常不是 systemd 的 postgresql 服务名），不重复安装/启动
        info('检测到本机 PostgreSQL 已在运行，只创建数据库与账号')
    else:
        runner.run(['systemctl', 'enable', '--now', 'postgresql'])
    # 幂等创建用户与数据库（密码来自自动生成，字符集安全）
    sql = (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{cfg.db_user}') THEN "
        f"CREATE ROLE {cfg.db_user} LOGIN PASSWORD '{cfg.db_password}'; "
        f"ELSE ALTER ROLE {cfg.db_user} WITH LOGIN PASSWORD '{cfg.db_password}'; END IF; "
        "END $$;"
    )
    runner.run(['sudo', '-u', 'postgres', 'psql', '-v', 'ON_ERROR_STOP=1', '-c', sql])
    exists = runner.run(
        ['sudo', '-u', 'postgres', 'psql', '-tAc',
         f"SELECT 1 FROM pg_database WHERE datname='{cfg.db_name}'"],
        capture=True,
    )
    if not cfg.dry_run and exists.stdout.strip() != '1':
        runner.run(['sudo', '-u', 'postgres', 'createdb', '-O', cfg.db_user, cfg.db_name])
    ok('数据库就绪')


def create_service_user(runner: Runner, cfg: Config) -> None:
    step('系统用户与目录')
    if runner.dry_run:
        info(f'[dry-run] 创建系统用户 {SERVICE_USER} 与目录 {cfg.app_dir}')
        return
    if not _user_exists(SERVICE_USER):
        runner.run(['useradd', '--system', '--home-dir', cfg.app_dir,
                    '--create-home', '--shell', '/usr/sbin/nologin', SERVICE_USER])
    Path(cfg.app_dir).mkdir(parents=True, exist_ok=True)
    ok(f'目录：{cfg.app_dir}')


def _user_exists(name: str) -> bool:
    try:
        import pwd
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def copy_project(runner: Runner, cfg: Config) -> None:
    step('同步项目代码')
    target = Path(cfg.app_dir)
    excludes = [
        '.git', '.venv', 'node_modules', '__pycache__', '.ruff_cache', '.gitignore',
        'BusinessCompetitionManagerWebFrontend/dist',
        'BusinessCompetitionManagerWebFrontend/node_modules',
        'BusinessCompetitionManagerWeb/media/uploads',
        'BusinessCompetitionManagerWeb/media/packages',
        'BusinessCompetitionManagerWeb/media/map_backgrounds',
        'BusinessCompetitionManagerWeb/media/messages',
        # 只排除仓库根目录的运行时目录（以 / 锚定）；否则会误伤
        # apps/global_/logs 这类同名的 Python 包，导致 ModuleNotFoundError
        '/logs', '/reports', '/.env',
    ]
    cmd = ['rsync', '-a']
    for pattern in excludes:
        cmd += ['--exclude', pattern]
    cmd += [f'{REPO_ROOT}/', f'{cfg.app_dir}/']
    runner.run(cmd)
    if not runner.dry_run:
        required = [
            'BusinessCompetitionManagerWeb/manage.py',
            'BusinessCompetitionManagerWeb/apps/global_/logs/__init__.py',
            'BusinessCompetitionManagerWeb/apps/competition/contracts/__init__.py',
        ]
        missing = [rel for rel in required if not (target / rel).exists()]
        if missing:
            die('代码同步不完整，缺少：' + '、'.join(missing)
                + '（请检查 rsync 排除规则）')
    ok('代码已同步（保留 .env / media 运行数据）')


def write_env(runner: Runner, cfg: Config) -> None:
    step('生成 .env')
    secure = 'true' if cfg.tls else 'false'
    proto = 'https' if cfg.tls else 'http'
    db_max = min(128, max(32, cfg.workers * cfg.threads))
    env_content = f"""## 由 deploy/debian/deploy.py 自动生成（{time.strftime('%Y-%m-%d %H:%M:%S')}）
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
SECURE_HSTS_SECONDS = '{'31536000' if cfg.tls else '0'}'
SECURE_HSTS_PRELOAD = 'false'
TRUST_X_FORWARDED_FOR = 'true'
TRUST_X_FORWARDED_PROTO = '{'true' if cfg.tls else 'false'}'
SESSION_COOKIE_SECURE = '{secure}'
CSRF_COOKIE_SECURE = '{secure}'

WEB_CONCURRENCY = '{cfg.workers}'
DB_MAX_CONCURRENT_REQUESTS = '{db_max}'
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
    env_path = Path(cfg.app_dir) / '.env'
    if runner.dry_run:
        info(f'[dry-run] 写入 {env_path}（SECRET_KEY/数据库密码已自动生成）')
        return
    env_path.write_text(env_content, encoding='utf-8')
    env_path.chmod(0o600)
    ok(f'.env 已生成：{env_path}')


def install_python_deps(runner: Runner, cfg: Config) -> None:
    step('安装后端依赖')
    app_dir = Path(cfg.app_dir)
    bootstrap = app_dir / '.bootstrap'
    runner.run(['python3', '-m', 'venv', str(bootstrap)])
    runner.run([str(bootstrap / 'bin' / 'pip'), 'install', '-q', '--upgrade', 'pip', 'uv'])
    uv = str(bootstrap / 'bin' / 'uv')
    # 项目要求 Python >= 3.12；Debian 12 自带 3.11，用 uv 下载独立 Python 3.12
    runner.run([uv, 'python', 'install', '3.12'])
    runner.run([uv, 'sync', '--frozen', '--python', '3.12', '--project', str(app_dir)])
    ok('后端依赖安装完成（.venv）')


def migrate(runner: Runner, cfg: Config) -> None:
    step('数据库迁移')
    app_dir = Path(cfg.app_dir)
    runner.run([str(app_dir / '.venv' / 'bin' / 'python'), 'manage.py', 'migrate', '--noinput'],
               cwd=app_dir / 'BusinessCompetitionManagerWeb')
    ok('迁移完成')


def create_superuser(runner: Runner, cfg: Config) -> None:
    step('创建管理员账号')
    app_dir = Path(cfg.app_dir)
    env = {
        'DJANGO_SUPERUSER_PASSWORD': cfg.admin_password,
        'DJANGO_SUPERUSER_EMAIL': cfg.admin_email,
    }
    result = runner.run(
        [str(app_dir / '.venv' / 'bin' / 'python'), 'manage.py', 'createsuperuser',
         '--noinput', '--username', cfg.admin_user],
        cwd=app_dir / 'BusinessCompetitionManagerWeb', env=env, check=False, capture=True)
    if runner.dry_run:
        return
    if result.returncode == 0:
        ok(f'管理员 {cfg.admin_user} 已创建')
    else:
        warn('管理员账号可能已存在（跳过创建）；如需重置密码请用 manage.py changepassword')


def build_frontend(runner: Runner, cfg: Config) -> None:
    step('构建前端')
    if not cfg.build_frontend:
        info('跳过（使用已有 dist；请确认前端产物已就位）')
        return
    front = Path(cfg.app_dir) / 'BusinessCompetitionManagerWebFrontend'
    if shutil.which('npm') is None:
        if not confirm('未检测到 Node.js，是否安装 Node.js 20？', True):
            die('缺少 Node.js，无法构建前端（可改 --no-frontend-build 使用预构建产物）')
        runner.run(['bash', '-c',
                    'curl -fsSL https://deb.nodesource.com/setup_20.x | bash -'])
        runner.run(['apt-get', 'install', '-y', 'nodejs'])
    runner.run(['npm', 'ci'], cwd=front)
    runner.run(['npm', 'run', 'build'], cwd=front)
    if not (front / 'dist' / 'index.html').exists():
        warn('未找到 dist/index.html，nginx 可能返回 404，请检查前端构建')
    ok('前端构建完成（BusinessCompetitionManagerWebFrontend/dist）')


def write_systemd(runner: Runner, cfg: Config) -> None:
    step('配置 systemd 服务')
    unit = f"""[Unit]
Description=BCM backend (waitress HTTP :{BACKEND_PORT} + daphne WS :{WS_PORT})
After=network.target postgresql.service
Wants=network.target

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
WorkingDirectory={cfg.app_dir}
# .env 由 Django 启动时 load_dotenv(REPO_ROOT/.env) 读取
ExecStart={cfg.app_dir}/.venv/bin/python scripts/run_servers.py --workers {cfg.workers} --threads {cfg.threads} --no-reload --host 127.0.0.1
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
    path = Path(f'/etc/systemd/system/{SERVICE_NAME}.service')
    if runner.dry_run:
        info(f'[dry-run] 写入 {path}')
        return
    path.write_text(unit, encoding='utf-8')
    runner.run(['systemctl', 'daemon-reload'])
    runner.run(['systemctl', 'enable', '--now', SERVICE_NAME])
    ok(f'{SERVICE_NAME}.service 已启动')


def write_nginx(runner: Runner, cfg: Config) -> None:
    step('配置 nginx')
    max_body_mb = 100
    conf = f"""upstream bcm_http {{
    server 127.0.0.1:{BACKEND_PORT};
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
    listen 80;
    listen [::]:80;
    server_name {cfg.domain};

    client_max_body_size {max_body_mb}m;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy same-origin always;

    root {cfg.app_dir}/BusinessCompetitionManagerWebFrontend/dist;
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
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        access_log off;
    }}
}}
"""
    export_path = Path(cfg.app_dir) / 'deploy' / 'nginx' / 'bcm.site.conf'
    if runner.dry_run:
        info(f'[dry-run] 生成站点配置（模式：{cfg.nginx_mode}）')
        return

    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(conf, encoding='utf-8')

    if cfg.nginx_mode == 'manual':
        info(f'已导出站点配置：{export_path}')
        info('请在 1Panel 中配置该站点（任选其一）：')
        print('  1) 1Panel → 网站 → 创建站点（PHP/静态），把上面的 server 内容替换进站点配置；')
        print('  2) 1Panel → 网站 → 反向代理：/api 指向 http://127.0.0.1:8000、'
              '/ws 指向 http://127.0.0.1:8001（需开启 WebSocket）；')
        print(f'  3) 前端根目录填：{cfg.app_dir}/BusinessCompetitionManagerWebFrontend/dist')
        return

    # manage 模式：优先 conf.d（1Panel/OpenResty 也常包含该目录），否则 sites-available
    conf_d = Path('/etc/nginx/conf.d')
    if conf_d.is_dir():
        target = conf_d / 'bcm.conf'
        target.write_text(conf, encoding='utf-8')
    else:
        available = Path('/etc/nginx/sites-available/bcm.conf')
        enabled = Path('/etc/nginx/sites-enabled/bcm.conf')
        available.write_text(conf, encoding='utf-8')
        if enabled.is_symlink() or enabled.exists():
            enabled.unlink()
        enabled.symlink_to(available)

    runner.run(['nginx', '-t'])
    runner.run(['systemctl', 'enable', '--now', 'nginx'])
    runner.run(['systemctl', 'reload', 'nginx'])
    ok('nginx 已配置并重载')


def configure_tls(runner: Runner, cfg: Config) -> None:
    step('HTTPS 证书')
    if cfg.ip_mode:
        info('纯 IP 部署：跳过 Let\'s Encrypt（不给 IP 签长期证书）；'
             '如必须 HTTPS，请改用域名或自签证书。')
        return
    if not cfg.tls:
        info('跳过（未启用 HTTPS；manual 模式请在 1Panel 里申请证书）')
        return
    if cfg.nginx_mode == 'manual':
        info('manual 模式：跳过 certbot，请在 1Panel 网站设置里一键申请 SSL')
        return
    if runner.dry_run:
        info(f'[dry-run] certbot --nginx -d {cfg.domain}（证书申请在真实部署时执行）')
        return
    result = runner.run(
        ['certbot', '--nginx', '-d', cfg.domain, '--non-interactive',
         '--agree-tos', '-m', cfg.admin_email, '--redirect'],
        check=False)
    if result.returncode == 0:
        ok(f'HTTPS 已启用：https://{cfg.domain}')
    else:
        warn('certbot 申请失败（通常是 DNS 未解析或 80 端口不通），站点仍可用 HTTP。'
             '稍后可手动执行：certbot --nginx -d ' + cfg.domain)


def setup_firewall(runner: Runner, cfg: Config) -> None:
    step('防火墙')
    if not cfg.firewall:
        info('跳过（未启用 ufw）')
        return
    if shutil.which('ufw') is None:
        runner.run(['apt-get', 'install', '-y', 'ufw'])
    runner.run(['ufw', 'allow', 'OpenSSH'])
    runner.run(['ufw', 'allow', 'Nginx Full'])
    runner.run(['ufw', '--force', 'enable'])
    ok('ufw 已启用（放行 SSH / 80 / 443）')


def fix_permissions(runner: Runner, cfg: Config) -> None:
    step('目录权限')
    runner.run(['chown', '-R', f'{SERVICE_USER}:{SERVICE_USER}', cfg.app_dir])
    ok(f'{cfg.app_dir} 归属 {SERVICE_USER}')


def health_check(runner: Runner, cfg: Config) -> None:
    step('健康检查')
    if runner.dry_run:
        info(f'[dry-run] 检查 http://127.0.0.1:{BACKEND_PORT}/api/health')
        return
    import urllib.request
    for attempt in range(30):
        try:
            with urllib.request.urlopen(
                    f'http://127.0.0.1:{BACKEND_PORT}/api/health', timeout=3) as resp:
                if resp.status == 200:
                    ok('后端健康检查通过')
                    return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    warn('后端 30 秒内未就绪，请查看：journalctl -u bcm -n 100 --no-pager')


def print_summary(cfg: Config) -> None:
    step('部署完成')
    proto = 'https' if cfg.tls else 'http'
    mode_note = '（纯 IP 模式，HTTP）' if cfg.ip_mode else ''
    lines = [
        f'站点：        {proto}://{cfg.domain}{mode_note}',
        f'安装目录：    {cfg.app_dir}',
        f'后端端口：    127.0.0.1:{BACKEND_PORT}（HTTP）/ {WS_PORT}（WS）',
        f'管理员账号：  {cfg.admin_user}',
        f'管理员密码：  {cfg.admin_password}',
        f'数据库：      {cfg.db_name}（用户 {cfg.db_user}）',
        '',
        '常用命令：',
        f'  systemctl status {SERVICE_NAME}',
        f'  systemctl restart {SERVICE_NAME}',
        f'  journalctl -u {SERVICE_NAME} -n 100 --no-pager',
        f'  tail -f /var/log/nginx/access.log',
        '',
        '配置修改：编辑 ' + f'{cfg.app_dir}/.env 后 systemctl restart {SERVICE_NAME}',
    ]
    text = '\n'.join(lines)
    print('\n' + text)
    summary_path = Path(cfg.app_dir) / 'DEPLOY_SUMMARY.txt'
    if not cfg.dry_run:
        summary_path.write_text(text + '\n', encoding='utf-8')
        summary_path.chmod(0o600)
        print(f'\n（以上信息已保存到 {summary_path}，权限 600）')


# ---------------------------------------------------------------- 入口
def main() -> int:
    parser = argparse.ArgumentParser(description='Debian 一键部署')
    parser.add_argument('--domain', help='站点域名（也可直接填 IP）')
    parser.add_argument('--ip', help='纯 IP 部署的访问地址（等价于 --domain 传 IP）')
    parser.add_argument('--app-dir', help='安装目录（默认 /opt/bcm）')
    parser.add_argument('--admin-user', help='管理员用户名')
    parser.add_argument('--admin-email', help='管理员邮箱')
    parser.add_argument('--db-mode', choices=['local', 'existing'], help='数据库模式')
    parser.add_argument('--nginx-mode', choices=['manage', 'manual'],
                        help='manage=脚本写 nginx 配置；manual=跳过（1Panel 里配）')
    parser.add_argument('--assume-detected', action='append', default=[],
                        choices=['nginx', 'openresty', 'postgres', 'onepanel', 'node', 'certbot'],
                        help='调试用：假设这些组件已存在（配合 --dry-run）')
    parser.add_argument('--db-host', help='已有数据库主机')
    parser.add_argument('--db-port', help='已有数据库端口')
    parser.add_argument('--db-name', help='数据库名')
    parser.add_argument('--db-user', help='数据库用户')
    parser.add_argument('--db-password', help='已有数据库密码（existing 模式）')
    parser.add_argument('--workers', type=int, help='HTTP worker 数（默认 CPU 核数）')
    parser.add_argument('--threads', type=int, help='每 worker 线程数（默认 8）')
    parser.add_argument('--tls', dest='tls', action='store_true', default=None,
                        help='申请 HTTPS 证书')
    parser.add_argument('--no-tls', dest='tls', action='store_false', help='不申请证书')
    parser.add_argument('--build-frontend', dest='build_frontend', action='store_true',
                        default=None)
    parser.add_argument('--no-frontend-build', dest='build_frontend', action='store_false')
    parser.add_argument('--firewall', dest='firewall', action='store_true', default=None)
    parser.add_argument('--no-firewall', dest='firewall', action='store_false')
    parser.add_argument('--yes', action='store_true', help='全部使用默认值/自动生成，不逐项询问')
    parser.add_argument('--dry-run', action='store_true', help='只打印计划，不执行')
    args = parser.parse_args()

    if args.dry_run:
        warn('dry-run：只打印计划，不修改系统')
    cfg = collect(args)
    preflight(cfg)

    runner = Runner(cfg.dry_run)
    print(f'\n即将部署到：{cfg.app_dir}')
    print(f'域名：{cfg.domain}　数据库：{cfg.db_mode}　HTTPS：{"是" if cfg.tls else "否"}　'
          f'构建前端：{"是" if cfg.build_frontend else "否"}')
    if not args.yes and not args.dry_run:
        if not confirm('确认开始部署？', True):
            print('已取消')
            return 0

    install_packages(runner, cfg, cfg.facts)
    setup_database(runner, cfg)
    create_service_user(runner, cfg)
    copy_project(runner, cfg)
    write_env(runner, cfg)
    install_python_deps(runner, cfg)
    migrate(runner, cfg)
    create_superuser(runner, cfg)
    build_frontend(runner, cfg)
    fix_permissions(runner, cfg)
    write_systemd(runner, cfg)
    write_nginx(runner, cfg)
    configure_tls(runner, cfg)
    setup_firewall(runner, cfg)
    health_check(runner, cfg)
    print_summary(cfg)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已中断')
        sys.exit(130)
