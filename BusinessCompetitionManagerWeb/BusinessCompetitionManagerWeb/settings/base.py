"""全局域 / 公共设置（重构方案 §5.3）。"""

from pathlib import Path
import os
import warnings

from dotenv import load_dotenv

# 项目根（BusinessCompetitionManagerWeb/ 后端根目录）
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 仓库根（.env 所在目录）
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / '.env')

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    warnings.warn(
        'SECRET_KEY 未设置或长度不足 32 字符：正在使用弱/不安全默认，切勿用于生产环境',
        RuntimeWarning,
    )

DEBUG = os.getenv('DEBUG', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

_ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '')
if _ALLOWED_HOSTS.strip():
    ALLOWED_HOSTS = [h.strip() for h in _ALLOWED_HOSTS.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    # 未显式配置且非 DEBUG：默认只允许本机访问。
    # 既保证本地开发/自检开箱可用，又不会对外开放（Django 对不在列表内的 Host 直接 400）。
    ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]']

# ---------------------------------------------------------------- 部署安全加固

# 是否信任 X-Forwarded-For（默认 False）。仅当部署在受信任的反向代理之后才应开启，
# 否则客户端可伪造该头绕过登录限流 / 污染审计日志 IP（见 apps.common.devices.client_ip）
TRUST_X_FORWARDED_FOR = os.getenv('TRUST_X_FORWARDED_FOR', 'false').strip().lower() in ('1', 'true', 'yes', 'on')

# Cookie 安全加固：Secure 标志生产（非 DEBUG）默认开启，可用环境变量覆盖；
# HttpOnly / SameSite 固定为安全值（HttpOnly 阻断 JS 读取会话/CSRF cookie）。
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', str(not DEBUG)).strip().lower() in ('1', 'true', 'yes', 'on')
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', str(not DEBUG)).strip().lower() in ('1', 'true', 'yes', 'on')
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# 仅当受信任反代转发协议头时，才让 Django 依据 X-Forwarded-Proto 判定 https
if os.getenv('TRUST_X_FORWARDED_PROTO', '').strip().lower() in ('1', 'true', 'yes', 'on'):
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ---------------------------------------------------------------- 应用

INSTALLED_APPS = [
    # daphne 置顶：接管 runserver，提供 ASGI/WebSocket（§5.1）
    'daphne',
    # 全局域应用（apps/global_）
    'apps.global_.accounts',
    'apps.global_.useradmin',  # 用户管理（账号增删改/重置密码，仅系统超管）
    'apps.global_.schools',
    'apps.global_.competitions',
    'apps.global_.memberships',
    'apps.global_.logs',
    'apps.global_.plugins',
    'apps.global_.packages',
    'apps.global_.teams',
    'apps.global_.invites',
    'apps.global_.profiles',
    'apps.global_.messages',  # 系统级站内信（label=inmail）
    'apps.global_.sysconfig',  # 系统设置（流量限制配置）
    'apps.global_.files',  # 文件上传服务（通用上传/地图背景/消息图片）
    # 比赛域容器包（无模型）：挂上它才会加载 apps/competition/management/commands
    # （provision_competition_db 建库/补迁移命令；见 docs/数据库优化.md）
    'apps.competition',
    # 比赛域应用（apps/competition，路由到 comp_<id>）
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
    # 第三方 / Django 内建
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
    # 数据库背压（限流）：多库路由下每请求最多占 全局库+比赛库 两条连接，
    # 并发过高先排队再服务，防止打爆 PostgreSQL max_connections（docs/数据库优化.md）
    'apps.common.middleware.DatabaseBackpressureMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # 比赛上下文解析（URL / X-Competition-Id → thread-local 比赛库 alias）
    'apps.common.middleware.CompetitionContextMiddleware',
    # API 每分钟限流（角色限额；需在 AuthenticationMiddleware 与比赛上下文之后）
    'apps.global_.sysconfig.middleware.RateLimitMiddleware',
    # 网络日志（§14.3：每次 API 交互脱敏记录）
    'apps.common.middleware.NetworkLogMiddleware',
    # /api/* 的 HTML 错误页 → 简洁中文 JSON（所有错误提示统一中文）
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

# ---------------------------------------------------------------- ASGI / WebSocket（§5.1）

ASGI_APPLICATION = 'BusinessCompetitionManagerWeb.asgi.application'

# 通道层（跨进程推送）：**多进程/多核部署下内存层不可用**——HTTP worker（waitress
# 进程）与 WS 进程（daphne）各自独立，InMemoryChannelLayer 的 group_send 只在本进程
# 有效，消息到不了 WS 进程。默认用 PostgreSQL 实现的跨进程通道层（零新增中间件，
# 见 apps/common/pg_channel_layer.py）；可选 redis / memory：
#   CHANNEL_LAYER_BACKEND=postgres|redis|memory
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

# ---------------------------------------------------------------- 密码验证

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------- 国际化

LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 上传文件（比赛包、插件文件留存，§9.4 审计）
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ---------------------------------------------------------------- CORS（Vue 开发联调）

CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
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

# ---------------------------------------------------------------- DRF + JWT（§12：REST + JWT）

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

# ---------------------------------------------------------------- 日志体系（§14）

# 脱敏字段黑名单（决策 D18：密码/token/邀请码原文一律不入日志）
LOG_REDACTED_KEYS = {
    'password', 'new_password', 'old_password', 'token', 'refresh', 'access',
    'authorization', 'cookie', 'secret', 'secret_key',
    'code', 'invite_code', 'join_code', 'team_code', 'activation_code',
}

# 请求/响应脱敏摘要最大长度
LOG_DIGEST_MAX_LENGTH = 2000

# ---------------------------------------------------------------- 进程模型（多核 CPU）

# 同时运行的 web worker 进程数（scripts/run_servers.py 启动时自动写入）。
# 多核吞吐 = worker 数 × 单核吞吐（单进程受 GIL 限制只能吃满一个核）。
WEB_CONCURRENCY = max(1, int(os.getenv('WEB_CONCURRENCY', '1')))

# ---------------------------------------------------------------- 数据库背压（过载保护）

# 同时处理的请求数上限（**全部 worker 合计**的全局预算）：多库路由下 DB 连接
# 峰值 ≈ 该值 × 2 + 后台；经验值 预算 × 2 + 后台 < PostgreSQL max_connections。
DB_MAX_CONCURRENT_REQUESTS = int(os.getenv('DB_MAX_CONCURRENT_REQUESTS', '32'))
# 每个 worker 进程内的信号量额度：全局预算按进程数分摊（进程内信号量无法跨进程），
# 保证 N 个 worker 合计仍不超过全局预算，不会因加核把 PG 打爆。
DB_MAX_CONCURRENT_REQUESTS_PER_WORKER = max(1, DB_MAX_CONCURRENT_REQUESTS // WEB_CONCURRENCY)
# 超出并发的请求最长排队秒数；超时返回 503 + Retry-After（快速失败，前端退避重试）
DB_BACKPRESSURE_TIMEOUT = float(os.getenv('DB_BACKPRESSURE_TIMEOUT', '10'))

# 日志留存（决策 D20：默认 3 年，只增不删；到期冷归档由运维脚本处理）
LOG_RETENTION_DAYS = 365 * 3

# ---------------------------------------------------------------- 版本与登录安全

# 服务端版本（前端启动 + 每 5 分钟轮询 /api/version 比对，不一致硬封锁）
APP_VERSION = os.getenv('APP_VERSION', '1.0.0')

# 登录失败限流：同一 用户名|IP 在窗口内失败 N 次 → 锁定 M 分钟（旧系统等价能力）
LOGIN_FAIL_LIMIT = int(os.getenv('LOGIN_FAIL_LIMIT', '10'))
LOGIN_FAIL_WINDOW_SECONDS = int(os.getenv('LOGIN_FAIL_WINDOW_SECONDS', '300'))
LOGIN_LOCK_SECONDS = int(os.getenv('LOGIN_LOCK_SECONDS', '900'))

# 测试运行器：销毁测试库前关闭 channel layer 的 PG 长连接（见 apps/common/test_runner.py）
TEST_RUNNER = 'apps.common.test_runner.GipfelTestRunner'
