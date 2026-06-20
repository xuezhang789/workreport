
import os
import base64
import hashlib
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}

# 项目根目录 (包含此 settings 文件的目录)
# Project root (directory containing this settings file)
BASE_DIR = Path(__file__).resolve().parent

# 安全警告：生产环境使用的密钥必须保密！
# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')

# 检查是否运行在开发服务器环境
# Check if we are running in a development server environment
import sys
IS_DEV_SERVER = 'runserver' in sys.argv
IS_TEST = 'test' in sys.argv or os.environ.get('DJANGO_TEST_MODE') == '1'

# 默认 DEBUG 设置：如果是开发服务器则为 True，否则为 False (默认为安全)
# Default DEBUG to True if running via runserver, otherwise False (secure by default)
DEFAULT_DEBUG = 'True' if (IS_DEV_SERVER or IS_TEST) else 'False'
DEBUG = env_bool('DJANGO_DEBUG', DEFAULT_DEBUG == 'True')

if not SECRET_KEY:
    if DEBUG or IS_TEST:
        # 仅开发环境的回退密钥
        # Fallback for dev only
        SECRET_KEY = 'django-insecure-replace-this-with-a-random-secret-key-for-dev'
    else:
        # 生产环境 (DEBUG=False) 必须配置 SECRET_KEY
        # In production (DEBUG=False), we must have a secret key
        raise ValueError("DJANGO_SECRET_KEY environment variable is required in production.")

ALLOWED_HOSTS = [host.strip() for host in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if host.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

PRODUCTION_SECURITY_DEFAULT = not (DEBUG or IS_TEST)
TRUST_PROXY_HEADERS = env_bool('DJANGO_TRUST_PROXY_HEADERS', PRODUCTION_SECURITY_DEFAULT)
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', PRODUCTION_SECURITY_DEFAULT)
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', PRODUCTION_SECURITY_DEFAULT)
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', PRODUCTION_SECURITY_DEFAULT)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = os.environ.get('DJANGO_SECURE_REFERRER_POLICY', 'same-origin')
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = int(os.environ.get(
    'DJANGO_SECURE_HSTS_SECONDS',
    31536000 if PRODUCTION_SECURITY_DEFAULT else 0,
))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', PRODUCTION_SECURITY_DEFAULT)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', PRODUCTION_SECURITY_DEFAULT)
if TRUST_PROXY_HEADERS:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    USE_X_FORWARDED_HOST = env_bool('DJANGO_USE_X_FORWARDED_HOST', False)


# 应用配置
# Trigger reload for new templatetags
INSTALLED_APPS = [
    'daphne', # 必须放在首位以支持 ASGI/Channels
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'channels', # WebSocket 支持
    'reports',  # 核心报表应用
    'core',     # 核心基础应用 (RBAC, Utils)
    'projects', # 项目管理应用
    'tasks',    # 任务管理应用
    'work_logs',# 日志记录应用
    'audit',    # 审计日志应用
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'core.middleware.RequestObservabilityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware', # 静态文件服务
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'core.middleware.SuperuserMFAMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'reports.middleware.TimingMiddleware', # 自定义性能计时中间件
    'audit.middleware.AuditMiddleware',    # 自定义审计日志中间件
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
                'reports.context_processors.admin_flags', # 自定义管理员标志
            ],
        },
    },
]

WSGI_APPLICATION = 'wsgi.application'
ASGI_APPLICATION = 'workreport.asgi.application'

# Channels / WebSocket 配置
CHANNEL_LAYER_BACKEND = os.environ.get(
    'CHANNEL_LAYER_BACKEND',
    'memory' if (DEBUG or IS_TEST) else 'redis',
).lower()
if CHANNEL_LAYER_BACKEND == 'redis':
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [os.environ.get(
                    'CHANNEL_REDIS_URL',
                    'redis://127.0.0.1:6379/1',
                )],
            },
        },
    }
elif CHANNEL_LAYER_BACKEND == 'memory':
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }
else:
    raise ValueError("CHANNEL_LAYER_BACKEND must be 'redis' or 'memory'")

CACHE_BACKEND = os.environ.get(
    'CACHE_BACKEND',
    'locmem' if (DEBUG or IS_TEST) else 'redis',
).lower()
if CACHE_BACKEND == 'redis':
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': os.environ.get(
                'CACHE_REDIS_URL',
                'redis://127.0.0.1:6379/2',
            ),
        },
    }
elif CACHE_BACKEND == 'locmem':
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'workreport-local-cache',
        },
    }
else:
    raise ValueError("CACHE_BACKEND must be 'redis' or 'locmem'")

# 数据库配置
# Database configuration is fail-closed in production. SQLite remains available
# for local development and tests only, unless an explicit escape hatch is set.
DB_ENGINE = os.environ.get('DB_ENGINE', 'django.db.backends.sqlite3')
DB_NAME = os.environ.get('DB_NAME')
DB_USER = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_HOST = os.environ.get('DB_HOST')
DB_PORT = os.environ.get('DB_PORT')
ALLOW_SQLITE_IN_PRODUCTION = env_bool('DJANGO_ALLOW_SQLITE_IN_PRODUCTION', False)

if DB_ENGINE == 'django.db.backends.sqlite3':
    database_name = Path(DB_NAME) if DB_NAME else BASE_DIR / 'db.sqlite3'
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': database_name,
        }
    }
    if PRODUCTION_SECURITY_DEFAULT and not ALLOW_SQLITE_IN_PRODUCTION:
        raise ImproperlyConfigured(
            'Production requires an explicit PostgreSQL/MySQL database. '
            'Set DB_ENGINE and DB_NAME, or set DJANGO_ALLOW_SQLITE_IN_PRODUCTION=True only for controlled checks.'
        )
else:
    missing_database_settings = [
        name for name, value in (
            ('DB_NAME', DB_NAME),
            ('DB_USER', DB_USER),
            ('DB_PASSWORD', DB_PASSWORD),
            ('DB_HOST', DB_HOST),
        )
        if not value
    ]
    if missing_database_settings:
        raise ImproperlyConfigured(
            f"Missing database settings: {', '.join(missing_database_settings)}"
        )
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': DB_NAME,
            'USER': DB_USER,
            'PASSWORD': DB_PASSWORD,
            'HOST': DB_HOST,
            'PORT': DB_PORT,
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', 60)),
            'CONN_HEALTH_CHECKS': True,
            'ATOMIC_REQUESTS': env_bool('DB_ATOMIC_REQUESTS', False),
        }
    }

BACKUP_ROOT = Path(os.environ.get('BACKUP_ROOT', BASE_DIR / 'backups'))
configured_encryption_keys = [
    key.strip()
    for key in os.environ.get('FIELD_ENCRYPTION_KEYS', '').split(',')
    if key.strip()
]
if not configured_encryption_keys:
    if PRODUCTION_SECURITY_DEFAULT:
        raise ImproperlyConfigured('FIELD_ENCRYPTION_KEYS is required in production')
    configured_encryption_keys = [
        base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode('utf-8')).digest()).decode('ascii')
    ]
FIELD_ENCRYPTION_KEYS = configured_encryption_keys
MFA_REQUIRED_FOR_SUPERUSERS = env_bool('MFA_REQUIRED_FOR_SUPERUSERS', PRODUCTION_SECURITY_DEFAULT)
OTP_TOTP_ISSUER = os.environ.get('OTP_TOTP_ISSUER', 'WorkReport')
MFA_MAX_ATTEMPTS = int(os.environ.get('MFA_MAX_ATTEMPTS', 10))
MFA_ATTEMPT_WINDOW_SECONDS = int(os.environ.get('MFA_ATTEMPT_WINDOW_SECONDS', 300))

LOG_FORMAT = os.environ.get('LOG_FORMAT', 'json' if PRODUCTION_SECURITY_DEFAULT else 'console')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
METRICS_TOKEN = os.environ.get('METRICS_TOKEN', '')
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'request_context': {'()': 'core.observability.RequestContextFilter'},
    },
    'formatters': {
        'json': {'()': 'core.observability.JsonFormatter'},
        'console': {
            'format': '%(levelname)s %(name)s [%(request_id)s] %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'filters': ['request_context'],
            'formatter': LOG_FORMAT if LOG_FORMAT in {'json', 'console'} else 'console',
        },
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        'django.server': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'workreport.request': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}

if SENTRY_DSN:
    try:
        import sentry_sdk
    except ImportError as exc:
        raise ImproperlyConfigured('SENTRY_DSN is set but sentry-sdk is not installed') from exc
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get('SENTRY_ENVIRONMENT', 'production'),
        release=os.environ.get('APP_RELEASE') or None,
        traces_sample_rate=float(os.environ.get('SENTRY_TRACES_SAMPLE_RATE', '0.05')),
        send_default_pii=False,
    )

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
STATIC_ROOT = BASE_DIR / 'collected_static'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
    BASE_DIR / 'staticfiles',
]

# Whitenoise 静态文件存储配置
# Whitenoise configuration
STATICFILES_STORAGE_BACKEND = (
    'django.contrib.staticfiles.storage.StaticFilesStorage'
    if (DEBUG or IS_TEST)
    else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
)
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': STATICFILES_STORAGE_BACKEND,
    },
}
WHITENOISE_MANIFEST_STRICT = not (DEBUG or IS_TEST)

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

# 附件存储配置 (Attachment Storage Configuration)
# 支持本地存储 (local) 和云存储 (oss, s3)
ATTACHMENT_STORAGE_CONFIG = {
    'default': 'local',
    'strategies': {
        'task_attachment': 'local',    # 任务附件存储策略
        'project_attachment': 'local', # 项目附件存储策略
    },
    'backends': {
        'local': {
            'type': 'local',
            'OPTIONS': {
                'location': str(MEDIA_ROOT),
                'base_url': MEDIA_URL,
            }
        },
        'oss': {
            'type': 'oss',
            'OPTIONS': {
                'bucket': os.environ.get('OSS_BUCKET', 'workreport-oss'),
                'endpoint': os.environ.get('OSS_ENDPOINT', 'oss-cn-hangzhou.aliyuncs.com'),
                'access_key': os.environ.get('OSS_ACCESS_KEY_ID') or os.environ.get('OSS_ACCESS_KEY'),
                'secret_key': os.environ.get('OSS_ACCESS_KEY_SECRET') or os.environ.get('OSS_SECRET_KEY'),
                'url_expiry': int(os.environ.get('OSS_URL_EXPIRY', 300)),
            }
        },
        's3': {
            'type': 's3',
            'OPTIONS': {
                'bucket': os.environ.get('S3_BUCKET', 'workreport-s3'),
                'region': os.environ.get('S3_REGION', 'us-east-1'),
                'endpoint_url': os.environ.get('S3_ENDPOINT_URL') or None,
                'access_key': os.environ.get('AWS_ACCESS_KEY_ID') or os.environ.get('S3_ACCESS_KEY'),
                'secret_key': os.environ.get('AWS_SECRET_ACCESS_KEY') or os.environ.get('S3_SECRET_KEY'),
                'session_token': os.environ.get('AWS_SESSION_TOKEN') or None,
                'addressing_style': os.environ.get('S3_ADDRESSING_STYLE', 'auto'),
                'server_side_encryption': os.environ.get('S3_SERVER_SIDE_ENCRYPTION') or None,
                'url_expiry': int(os.environ.get('S3_URL_EXPIRY', 300)),
            }
        }
    }
}

# --- Celery Configuration ---
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = env_bool('CELERY_TASK_ACKS_LATE', PRODUCTION_SECURITY_DEFAULT)
CELERY_TASK_REJECT_ON_WORKER_LOST = env_bool('CELERY_TASK_REJECT_ON_WORKER_LOST', PRODUCTION_SECURITY_DEFAULT)
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.environ.get('CELERY_WORKER_PREFETCH_MULTIPLIER', 1))
CELERY_WORKER_MAX_TASKS_PER_CHILD = int(os.environ.get('CELERY_WORKER_MAX_TASKS_PER_CHILD', 200))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get('CELERY_TASK_SOFT_TIME_LIMIT', 300))
CELERY_TASK_TIME_LIMIT = int(os.environ.get('CELERY_TASK_TIME_LIMIT', 360))
CELERY_TASK_DEFAULT_QUEUE = os.environ.get('CELERY_TASK_DEFAULT_QUEUE', 'default')
CELERY_TASK_DEFAULT_EXCHANGE = CELERY_TASK_DEFAULT_QUEUE
CELERY_TASK_DEFAULT_ROUTING_KEY = CELERY_TASK_DEFAULT_QUEUE
CELERY_TASK_ROUTES = {
    'reports.tasks.generate_export_file_task': {'queue': os.environ.get('CELERY_EXPORT_QUEUE', 'exports')},
    'reports.tasks.send_email_async_task': {'queue': os.environ.get('CELERY_EMAIL_QUEUE', 'email')},
    'reports.tasks.process_notification_delivery_task': {'queue': os.environ.get('CELERY_NOTIFICATION_QUEUE', 'notifications')},
    'reports.tasks.dispatch_pending_notification_deliveries_task': {'queue': os.environ.get('CELERY_NOTIFICATION_QUEUE', 'notifications')},
}
CELERY_TASK_LOCK_TIMEOUT_SECONDS = int(os.environ.get('CELERY_TASK_LOCK_TIMEOUT_SECONDS', 600))
EXPORT_JOB_STALE_MINUTES = int(os.environ.get('EXPORT_JOB_STALE_MINUTES', 60))
UPLOAD_SESSION_TTL_HOURS = int(os.environ.get('UPLOAD_SESSION_TTL_HOURS', 24))
NOTIFICATION_OUTBOX_SYNC = env_bool('NOTIFICATION_OUTBOX_SYNC', IS_TEST)
NOTIFICATION_OUTBOX_MAX_ATTEMPTS = int(os.environ.get('NOTIFICATION_OUTBOX_MAX_ATTEMPTS', 8))
DIRECT_UPLOAD_ENABLED = env_bool('DIRECT_UPLOAD_ENABLED', False)
DIRECT_UPLOAD_EXPIRES_SECONDS = int(os.environ.get('DIRECT_UPLOAD_EXPIRES_SECONDS', 900))

from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    'dispatch-notification-outbox': {
        'task': 'reports.tasks.dispatch_pending_notification_deliveries_task',
        'schedule': crontab(minute='*'),
        'args': (100,),
    },
    'cleanup-old-logs-daily': {
        'task': 'reports.tasks.cleanup_old_logs_task',
        'schedule': crontab(hour=3, minute=0), # Run at 3 AM daily
        'args': (180,), # Keep 180 days
    },
    'runtime-maintenance-hourly': {
        'task': 'reports.tasks.runtime_maintenance_task',
        'schedule': crontab(minute=15),
    },
}
