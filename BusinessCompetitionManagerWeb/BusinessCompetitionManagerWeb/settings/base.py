"""全局域 / 公共设置（重构方案 §5.3）。"""

from pathlib import Path
import os

from dotenv import load_dotenv

# 项目根（BusinessCompetitionManagerWeb/ 后端根目录）
BASE_DIR = Path(__file__).resolve().parent.parent.parent
# 仓库根（.env 所在目录）
REPO_ROOT = BASE_DIR.parent

load_dotenv(REPO_ROOT / '.env')

SECRET_KEY = os.getenv('SECRET_KEY')

DEBUG = True

ALLOWED_HOSTS = ['*'] if DEBUG else []

# ---------------------------------------------------------------- 应用

INSTALLED_APPS = [
    # daphne 置顶：接管 runserver，提供 ASGI/WebSocket（§5.1）
    'daphne',
    # 全局域应用（apps/global_）
    'apps.global_.accounts',
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
    # 第三方 / Django 内建
    'corsheaders',
    'rest_framework',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
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

# 通道层：开发用内存层（单进程）；生产多进程时改用 Redis：
# {'BACKEND': 'channels_redis.core.RedisChannelLayer', 'CONFIG': {'hosts': [('127.0.0.1', 6379)]}}
CHANNEL_LAYERS = {
    'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
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

# ---------------------------------------------------------------- 数据库背压（过载保护）

# 同时处理的请求数上限（多库路由下 DB 连接峰值 ≈ 该值 × 2 + 后台）：
# 经验值 DB_MAX_CONCURRENT_REQUESTS × 2 + 后台 < PostgreSQL max_connections
DB_MAX_CONCURRENT_REQUESTS = int(os.getenv('DB_MAX_CONCURRENT_REQUESTS', '32'))
# 超出并发的请求最长排队秒数；超时返回 503 + Retry-After（快速失败，前端退避重试）
DB_BACKPRESSURE_TIMEOUT = float(os.getenv('DB_BACKPRESSURE_TIMEOUT', '10'))

# 日志留存（决策 D20：默认 3 年，只增不删；到期冷归档由运维脚本处理）
LOG_RETENTION_DAYS = 365 * 3
