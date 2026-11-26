"""全局域 / 公共设置（重构方案 §5.3）。"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
import os
import sys
import warnings

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent
load_dotenv(REPO_ROOT / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', '').strip()
if not SECRET_KEY or len(SECRET_KEY) < 32 or SECRET_KEY.startswith('django-insecure-'):
    # 开发（DEBUG）只告警；生产必须显式配置强密钥，否则直接拒绝启动
    if os.getenv('DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on'):
        warnings.warn(
            'SECRET_KEY 未设置或为弱密钥：仅限本地开发，切勿用于生产环境',
            RuntimeWarning,
        )
    else:
        raise ImproperlyConfigured(
            'SECRET_KEY 必须通过环境变量配置为 ≥32 字符的随机值（不能以 django-insecure- 开头）')

DEBUG = os.getenv('DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

_ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '')
if _ALLOWED_HOSTS.strip():
    ALLOWED_HOSTS = [h.strip() for h in _ALLOWED_HOSTS.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']

# ---------------------------------------------------------------- 安全响应头
X_FRAME_OPTIONS = os.getenv('X_FRAME_OPTIONS', 'DENY')
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.getenv('SECURE_REFERRER_POLICY', 'same-origin')
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if origin.strip()
]
# HTTPS 部署时开启（反代终止 TLS 时配合 TRUST_X_FORWARDED_PROTO=1）
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
# 健康检查必须允许内网 HTTP 直连，否则 deploy/status 会因为 301 一直判定未就绪
SECURE_REDIRECT_EXEMPT = [r'^api/health$']
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0') or 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

# 是否信任 X-Forwarded-For（默认 False）：仅在受信任反代之后才开启，否则客户端可伪造该头
# 绕过登录限流 / 污染审计日志 IP（见 apps.common.devices.client_ip）
TRUST_X_FORWARDED_FOR = os.getenv('TRUST_X_FORWARDED_FOR', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

# Cookie 安全加固：Secure（非 DEBUG 默认开，可环境变量覆盖）；HttpOnly/SameSite 固定安全值
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', str(not DEBUG)).strip().lower() in ('1', 'true', 'yes', 'on')
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', str(not DEBUG)).strip().lower() in ('1', 'true', 'yes', 'on')
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

if os.getenv('TRUST_X_FORWARDED_PROTO', '').strip().lower() in ('1', 'true', 'yes', 'on'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    # daphne 置顶：接管 runserver，提供 ASGI/WebSocket（§5.1）
    'daphne',
    'apps.global_.accounts',
    'apps.global_.useradmin',
    'apps.global_.schools',
    'apps.global_.competitions',
    'apps.global_.jobs',
    'apps.global_.memberships',
    'apps.global_.logs',
    'apps.global_.plugins',
    'apps.global_.packages',
    'apps.global_.teams',
    'apps.global_.invites',
    'apps.global_.profiles',
    'apps.global_.messages',
    'apps.global_.sysconfig',
    'apps.global_.files',
    # 比赛域容器包（无模型）：挂上它才会加载 apps/competition/management/commands（建库/补迁移命令）
    'apps.competition',
    'apps.competition.companies',
    'apps.competition.industries',
    'apps.competition.contracts',
    'apps.competition.fiscal',
    'apps.competition.ledger',
    'apps.competition.fieldlogs',
    'apps.competition.basedata',
    'apps.competition.messages',
    'apps.competition.audit',
    'apps.competition.settlement',
    'apps.competition.stock',  # 股票模块（契约：股票模块与同步优化.md §2）
    'apps.competition.regions',  # 区域与消费者需求（2026-10 决策：补齐旧功能）
    'apps.competition.tools',  # 工具箱（计时器等）
    'corsheaders',
    'rest_framework',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.postgres',  # GinIndex 依赖（contracts.parties JSONB GIN 索引）
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

# 自定义用户模型（§6.1 users：一账号一学校，身份在 membership）
AUTH_USER_MODEL = 'accounts.User'

MIDDLEWARE = [
    # 数据库背压：每请求最多占 2 条连接，并发过高先排队，防止打爆 PG max_connections（docs/数据库优化.md）
    'apps.common.middleware.DatabaseBackpressureMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.common.middleware.CompetitionContextMiddleware',
    # API 每分钟限流（角色限额；需在 AuthenticationMiddleware 与比赛上下文之后）
    'apps.global_.sysconfig.middleware.RateLimitMiddleware',
    'apps.common.middleware.NetworkLogMiddleware',
    'apps.common.middleware.ApiErrorHtmlMiddleware',
]

ROOT_URLCONF = 'BusinessCompetitionManagerWeb.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'BusinessCompetitionManagerWeb.wsgi.application'

ASGI_APPLICATION = 'BusinessCompetitionManagerWeb.asgi.application'

# ---------------------------------------------------------------- 缓存层（进程内）
# 决策（2026-11）：不引入 Redis，用 Django 进程内缓存。
# 代价：每个 waitress worker 各一份缓存（N 个 worker 各有一份，命中率按 worker 摊薄）；
# 收益：零外部依赖、零运维，且目录型接口的冷启动开销被完全消除。
# 缓存内容仅限「读多写少」的目录数据（合同类型 schema、公司列表），实时数据不缓存。
CACHE_DEFAULT_TIMEOUT = int(os.getenv('CACHE_DEFAULT_TIMEOUT', '300'))

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'bcm-locmem',
        'TIMEOUT': CACHE_DEFAULT_TIMEOUT,
    },
}

# 通道层（跨进程推送）：**多进程/多核下内存层不可用**——HTTP worker 与 WS 进程各自独立，
# InMemoryChannelLayer 的 group_send 只在本进程有效。默认 PG 实现（apps/common/pg_channel_layer.py，
# 零新增中间件）；可选 CHANNEL_LAYER_BACKEND=redis|memory。
CHANNEL_LAYER_BACKEND = os.getenv('CHANNEL_LAYER_BACKEND', 'postgres').strip().lower()

if CHANNEL_LAYER_BACKEND == 'memory':
    # 仅限单进程开发/测试（多进程部署会丢推送）
    CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
    }
elif CHANNEL_LAYER_BACKEND == 'redis':
    # 需安装 channels-redis 并提供 REDIS_URL
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'apps.common.pg_channel_layer.PostgresChannelLayer',
            'CONFIG': {
                # 推送拉取间隔（秒）：推送延迟 ≤ 该值；客户端按信号去抖 1.5s，0.1s 足够
                'poll_interval': float(os.getenv('CHANNEL_POLL_INTERVAL', '0.1')),
            },
        },
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 上传文件（比赛包、插件文件留存，§9.4 审计）
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5173,http://127.0.0.1:5173',
    ).split(',')
    if origin.strip()
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    'accept',
    'authorization',
    'content-type',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-competition-id',
    'x-device-screen',
    'x-trace-id',
]

from datetime import timedelta  # noqa: E402

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'apps.global_.accounts.authentication.GipfelJWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'EXCEPTION_HANDLER': 'apps.common.errors.gipfel_exception_handler',
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=6),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'UPDATE_LAST_LOGIN': True,
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'uid',
    'TOKEN_OBTAIN_SERIALIZER': 'apps.global_.accounts.serializers.GipfelTokenObtainPairSerializer',
}

# ---------------------------------------------------------------- 业务限制（.env 可调）
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, '') or default)
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: str) -> list:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


# 上传（通用文件 / 站内信图片）
UPLOAD_MAX_BYTES = _env_int('UPLOAD_MAX_BYTES', 100 * 1024 * 1024)
MESSAGE_IMAGE_MAX_BYTES = _env_int('MESSAGE_IMAGE_MAX_BYTES', 5 * 1024 * 1024)
UPLOAD_ALLOWED_EXTENSIONS = _env_list(
    'UPLOAD_ALLOWED_EXTENSIONS',
    'png,jpg,jpeg,gif,webp,pdf,xlsx,csv,zip,txt,md',
)

# 比赛包导入（上传体积 / 解压后体积 / 文件数）
PACKAGE_MAX_BYTES = _env_int('PACKAGE_MAX_BYTES', 100 * 1024 * 1024)
PACKAGE_MAX_FILES = _env_int('PACKAGE_MAX_FILES', 3000)
PACKAGE_MAX_UNCOMPRESSED_BYTES = _env_int(
    'PACKAGE_MAX_UNCOMPRESSED_BYTES', 300 * 1024 * 1024)

# 合同列表/同步/详情
CONTRACT_PAGE_SIZE = _env_int('CONTRACT_PAGE_SIZE', 50)
CONTRACT_PAGE_SIZE_MAX = _env_int('CONTRACT_PAGE_SIZE_MAX', 200)
CONTRACT_SYNC_LIMIT = _env_int('CONTRACT_SYNC_LIMIT', 500)
CONTRACT_SYNC_LIMIT_MAX = _env_int('CONTRACT_SYNC_LIMIT_MAX', 1000)
CONTRACT_TIMELINE_MAX = _env_int('CONTRACT_TIMELINE_MAX', 300)
CONTRACT_CHECKS_MAX = _env_int('CONTRACT_CHECKS_MAX', 200)
CONTRACT_OVERDUE_HOURS = _env_int('CONTRACT_OVERDUE_HOURS', 24)
CONTRACT_FREEZE_TIMEOUT_HOURS = _env_int('CONTRACT_FREEZE_TIMEOUT_HOURS', 24)

# 工具箱计时器
TIMER_MAX_DURATION_DAYS = _env_int('TIMER_MAX_DURATION_DAYS', 30)

# 基础数据列表分页
BASEDATA_PAGE_SIZE = _env_int('BASEDATA_PAGE_SIZE', 200)
BASEDATA_PAGE_SIZE_MAX = _env_int('BASEDATA_PAGE_SIZE_MAX', 500)

# 进程内缓存 TTL（秒）
CACHE_TTL_CONTRACT_TYPES = _env_int('CACHE_TTL_CONTRACT_TYPES', 600)
CACHE_TTL_COMPANY_LIST = _env_int('CACHE_TTL_COMPANY_LIST', 15)
CACHE_TTL_BASEDATA = _env_int('CACHE_TTL_BASEDATA', 20)
CACHE_TTL_INDUSTRY_FIELDS = _env_int('CACHE_TTL_INDUSTRY_FIELDS', 60)

# 日志留存（prune 命令默认值）
NETWORK_LOG_RETENTION_DAYS = _env_int('NETWORK_LOG_RETENTION_DAYS', 30)
NETWORK_LOG_KEEP_ROWS = _env_int('NETWORK_LOG_KEEP_ROWS', 200000)
# 测试运行器会回滚事务，异步线程写入会引用已回滚的用户；测试环境强制同步。
TESTING = 'test' in sys.argv
# 网络日志异步批量写：请求线程不直接写全局库；设为 0 可退回同步（排障用）
NETWORK_LOG_ASYNC = os.getenv('NETWORK_LOG_ASYNC', '1') == '1' and not TESTING
BROADCAST_EVENT_RETENTION_DAYS = _env_int('BROADCAST_EVENT_RETENTION_DAYS', 7)
BROADCAST_EVENT_KEEP_ROWS = _env_int('BROADCAST_EVENT_KEEP_ROWS', 100000)

# 脱敏字段黑名单（决策 D18：密码/token/邀请码原文一律不入日志）
LOG_REDACTED_KEYS = {
    'password', 'new_password', 'old_password', 'token', 'refresh', 'access',
    'authorization', 'cookie', 'secret', 'secret_key',
    'code', 'invite_code', 'join_code', 'team_code', 'activation_code',
}

# 网络日志里请求/响应摘要的最大长度（字节数级字符）：400 人规模下日志行宽直接影响
# 表体积与清理成本，可用环境变量调小（如 500）；调小不丢可追溯性，只压缩摘要。
LOG_DIGEST_MAX_LENGTH = int(os.getenv('LOG_DIGEST_MAX_LENGTH', '2000'))

# web worker 进程数（scripts/run_servers.py 启动时自动写入）；多核吞吐 = worker 数 × 单核吞吐（GIL）
WEB_CONCURRENCY = max(1, int(os.getenv('WEB_CONCURRENCY', '1')))

# 同时处理请求上限（**全部 worker 合计**）：DB 连接峰值 ≈ 该值 × 2 + 后台，需 < PG max_connections
DB_MAX_CONCURRENT_REQUESTS = int(os.getenv('DB_MAX_CONCURRENT_REQUESTS', '32'))
# 每 worker 的额度：进程内信号量无法跨进程，故按进程数分摊，保证 N 个 worker 合计不超预算
DB_MAX_CONCURRENT_REQUESTS_PER_WORKER = max(1, DB_MAX_CONCURRENT_REQUESTS // WEB_CONCURRENCY)
# 超出并发的请求最长排队秒数；超时 503 + Retry-After（快速失败，前端退避重试）
DB_BACKPRESSURE_TIMEOUT = float(os.getenv('DB_BACKPRESSURE_TIMEOUT', '10'))

# 日志留存（决策 D20：默认 3 年，只增不删；到期冷归档由运维脚本处理）
LOG_RETENTION_DAYS = 365 * 3

# 服务端版本（前端启动 + 每 5 分钟轮询 /api/version 比对，不一致硬封锁）
APP_VERSION = os.getenv('APP_VERSION', '1.0.0')

# 登录失败限流：同一 用户名|IP 在窗口内失败 N 次 → 锁定 M 分钟（旧系统等价能力）
LOGIN_FAIL_LIMIT = int(os.getenv('LOGIN_FAIL_LIMIT', '10'))
LOGIN_FAIL_WINDOW_SECONDS = int(os.getenv('LOGIN_FAIL_WINDOW_SECONDS', '300'))
LOGIN_LOCK_SECONDS = int(os.getenv('LOGIN_LOCK_SECONDS', '900'))

# 测试运行器：销毁测试库前关闭 channel layer 的 PG 长连接（见 apps/common/test_runner.py）
TEST_RUNNER = 'apps.common.test_runner.GipfelTestRunner'
