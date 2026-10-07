"""
BusinessCompetitionManagerWeb 项目的 Django 设置。

由 'django-admin startproject' 使用 Django 6.1.1 生成。

有关此文件的更多信息，请参阅
https://docs.djangoproject.com/en/6.1/topics/settings/

有关全部设置及其取值的完整列表，请参阅
https://docs.djangoproject.com/en/6.1/ref/settings/
"""

from pathlib import Path

import os
from dotenv import load_dotenv

## 加载 .env 文件
load_dotenv()

# 在项目内构建路径的方式如下：BASE_DIR / 'subdir'。
BASE_DIR = Path(__file__).resolve().parent.parent


# 快速入门开发设置 - 不适用于生产环境
# 请参阅 https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/

# 安全警告：请妥善保管生产环境中使用的密钥！
## 从 .env 文件中读取 SECRET_KEY
SECRET_KEY = os.getenv('SECRET_KEY')

# 安全警告：请勿在生产环境中开启调试模式！
DEBUG = True

ALLOWED_HOSTS = []


# 应用定义

INSTALLED_APPS = [
    'corsheaders',
    'rest_framework',
    'BusinessCompetitionManager.apps.BusinesscompetitionmanagerConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
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


# 数据库
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases
##从.env文件中读取数据库配置

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DATABASES_NAME'),
        'USER': os.getenv('DATABASES_USER'),
        'PASSWORD': os.getenv('DATABASES_PASSWORD'),
        'HOST': os.getenv('DATABASES_HOST'),
        'PORT': os.getenv('DATABASES_PORT'),
    }
}


# 密码验证
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# 国际化
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = True


# 静态文件（CSS、JavaScript、图片）
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'


# 邮件
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}


# 跨域资源共享（CORS），供前端 Vue 开发联调
# 允许 Vite 开发服务器的来源访问 API
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]
CORS_ALLOW_CREDENTIALS = True

# Django REST Framework 配置
REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        # 演示阶段放开为允许任意访问，生产环境请改为登录/令牌校验
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}
