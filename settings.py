import os
from pathlib import Path

# Project root (directory containing this settings file)
BASE_DIR = Path(__file__).resolve().parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-replace-this-with-a-random-secret-key-for-dev')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')


# Trigger reload for new templatetags
INSTALLED_APPS = [
    'daphne', # Must be first
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'reports',
    'core',
    'projects',
    'tasks',
    'work_logs',
    'audit',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'reports.middleware.TimingMiddleware',
    'audit.middleware.AuditMiddleware',
]

ROOT_URLCONF = 'urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'reports.context_processors.admin_flags',
            ],
        },
    },
]

WSGI_APPLICATION = 'wsgi.application'
ASGI_APPLICATION = 'asgi.application'

CHANNEL_LAYERS = {
    "default": {
        # "BACKEND": "channels_redis.core.RedisChannelLayer",
        # "CONFIG": {
        #     "hosts": [("127.0.0.1", 6379)],
        # },
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Ho_Chi_Minh'

USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Whitenoise configuration
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

SLA_REMIND_HOURS = 24  # 任务 SLA 提前提醒时间（小时）

# 邮件通知配置：开发环境默认使用控制台，生产环境默认使用 SMTP
default_email_backend = 'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', default_email_backend)
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))  # TLS 587 / SSL 465

# 解析布尔开关，防止同时开启 TLS/SSL
env_use_ssl = os.environ.get('EMAIL_USE_SSL')
env_use_tls = os.environ.get('EMAIL_USE_TLS')
EMAIL_USE_SSL = (env_use_ssl or '').lower() == 'true'
EMAIL_USE_TLS = (env_use_tls or '').lower() == 'true' if env_use_tls is not None else True
if EMAIL_USE_SSL and EMAIL_USE_TLS:
    raise ValueError("EMAIL_USE_SSL 与 EMAIL_USE_TLS 不能同时为 True，请仅保留一种安全传输方式")
# 如果未明确配置，则根据端口智能选择
if not env_use_ssl and not env_use_tls:
    if EMAIL_PORT == 587:
        EMAIL_USE_TLS = True
        EMAIL_USE_SSL = False
    elif EMAIL_PORT == 465:
        EMAIL_USE_SSL = True
        EMAIL_USE_TLS = False

EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')  # 发信账号
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')  # 授权码/密码
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER)
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 10))
EMAIL_SUBJECT_PREFIX = os.environ.get('EMAIL_SUBJECT_PREFIX', '[WorkReport] ')

# 在生产 SMTP 场景下缺少凭证时给出显式警告
if EMAIL_BACKEND.endswith('smtp.EmailBackend') and (not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD):
    # import warnings
    # warnings.warn("SMTP 邮件发送启用，但 EMAIL_HOST_USER / EMAIL_HOST_PASSWORD 未配置，将导致发送失败。")
    pass

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/reports/workbench/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# SLA 阈值（小时）：可通过 SystemSetting.sla_thresholds 覆盖
SLA_TIGHT_HOURS_DEFAULT = 6
SLA_CRITICAL_HOURS_DEFAULT = 2
