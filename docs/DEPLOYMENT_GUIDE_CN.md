# WorkReport 部署与上线教程

本文档基于当前代码仓库整理，适用于 WorkReport 的测试、预发布和生产部署。系统是 Django 5.2 应用，使用 ASGI/Daphne 承载 HTTP 与 WebSocket，Celery 处理异步任务，Redis 用于缓存、Channel Layer 与任务队列，生产环境推荐 PostgreSQL。

---

## 1. 架构与运行组件

核心组件：

- Web：`daphne -b 0.0.0.0 -p 8000 workreport.asgi:application`
- Worker：`celery -A celery_app worker -l info -Q default,exports,email,notifications`
- Beat：`celery -A celery_app beat -l info`
- 数据库：PostgreSQL 13+ 推荐；MySQL 8 可用但需单独安装驱动
- Redis：缓存、WebSocket Channel Layer、Celery Broker/Result Backend
- Nginx：反向代理、静态文件、上传大小控制、WebSocket Upgrade
- 可观测性：JSON 日志、`X-Request-ID`、Prometheus `/metrics`、Sentry

关键端点：

- `/healthz`：进程存活检查，不访问外部依赖
- `/readyz`：数据库与缓存就绪检查，失败返回 503
- `/metrics`：Prometheus 指标，生产环境必须配置 `METRICS_TOKEN`

---

## 2. 环境要求

推荐版本：

- Linux：Ubuntu 22.04+ / Debian 12+ / CentOS Stream 9+
- Python：3.12 推荐，CI 与 Dockerfile 均使用 3.12
- PostgreSQL：13+，Compose 示例使用 16
- Redis：6+
- Nginx：1.20+

系统包示例：

```bash
sudo apt update
sudo apt install -y \
  git nginx redis-server \
  python3.12 python3.12-venv python3.12-dev \
  build-essential pkg-config libpq-dev postgresql-client \
  default-libmysqlclient-dev default-mysql-client
```

数据库驱动说明：

- `requirements.txt` 包含 Django、Daphne、Celery、Redis、Sentry、安全扫描、对象存储等项目依赖。
- 生产使用 PostgreSQL 时，还需要安装 `psycopg[binary]` 或 `psycopg2-binary`。
- 生产使用 MySQL 时，还需要安装 `mysqlclient`。
- 如果基于当前 Dockerfile 构建生产镜像，应把所选数据库驱动纳入镜像依赖，否则容器连接 PostgreSQL/MySQL 时会缺少驱动。

---

## 3. 生产配置

复制配置模板：

```bash
cp .env.example .env
```

最低生产配置示例：

```ini
DJANGO_SECRET_KEY=请生成一个长随机字符串
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=workreport.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://workreport.example.com
DJANGO_TRUST_PROXY_HEADERS=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=True

DB_ENGINE=django.db.backends.postgresql
DB_NAME=workreport
DB_USER=workreport
DB_PASSWORD=请使用强密码
DB_HOST=127.0.0.1
DB_PORT=5432
DB_CONN_MAX_AGE=60
DJANGO_ALLOW_SQLITE_IN_PRODUCTION=False

CACHE_BACKEND=redis
CACHE_REDIS_URL=redis://127.0.0.1:6379/2
CHANNEL_LAYER_BACKEND=redis
CHANNEL_REDIS_URL=redis://127.0.0.1:6379/1
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

LOG_FORMAT=json
LOG_LEVEL=INFO
METRICS_TOKEN=请生成独立随机令牌
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
APP_RELEASE=

FIELD_ENCRYPTION_KEYS=请生成Fernet密钥
MFA_REQUIRED_FOR_SUPERUSERS=True
OTP_TOTP_ISSUER=WorkReport

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
EMAIL_HOST_USER=notice@example.com
EMAIL_HOST_PASSWORD=SMTP授权码
DEFAULT_FROM_EMAIL=notice@example.com

NOTIFICATION_OUTBOX_SYNC=False
NOTIFICATION_OUTBOX_MAX_ATTEMPTS=8
CELERY_TASK_ACKS_LATE=True
CELERY_TASK_REJECT_ON_WORKER_LOST=True
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_WORKER_MAX_TASKS_PER_CHILD=200
CELERY_TASK_SOFT_TIME_LIMIT=300
CELERY_TASK_TIME_LIMIT=360
EXPORT_JOB_STALE_MINUTES=60
UPLOAD_SESSION_TTL_HOURS=24
```

生成敏感字段加密密钥：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

密钥轮换方式：

```ini
FIELD_ENCRYPTION_KEYS=新密钥,旧密钥
```

新密钥必须放在第一位。完成数据重加密、备份校验和恢复演练前，不要删除旧密钥。

---

## 4. 附件与对象存储

默认附件策略是本地磁盘：

- 项目附件、任务附件、合同、收款二维码均由 Django 鉴权视图返回。
- Nginx 不应直接公开 `/media/` 下的业务文件。
- 开发环境只公开 `/media/avatars/` 头像路径。

生产建议使用 S3 兼容存储或阿里云 OSS，并通过系统设置 `attachment_storage_config` 将 `task_attachment`、`project_attachment` 策略切换为 `s3` 或 `oss`。

S3 / MinIO 示例：

```ini
S3_BUCKET=workreport-prod
S3_REGION=ap-southeast-1
S3_ENDPOINT_URL=
S3_ADDRESSING_STYLE=auto
S3_SERVER_SIDE_ENCRYPTION=AES256
S3_URL_EXPIRY=300
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=
```

阿里云 OSS 示例：

```ini
OSS_BUCKET=workreport-prod
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_URL_EXPIRY=300
```

浏览器直传对象存储：

```ini
DIRECT_UPLOAD_ENABLED=True
DIRECT_UPLOAD_EXPIRES_SECONDS=900
```

直传只应在默认附件后端为 `s3` 或 `oss` 时开启。上线前必须验证上传、签名下载、删除、重复文件名、超大文件、过期会话和旧附件回读。

---

## 5. 首次初始化

安装依赖：

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip wheel setuptools
python -m pip install -r requirements.txt
python -m pip install "psycopg[binary]"
```

初始化数据库与基础数据：

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py init_project_phases
python manage.py init_rbac
python manage.py init_role_templates
python manage.py rebuild_search_index
python manage.py collectstatic --noinput
```

模板初始化二选一：

- 推荐：`python manage.py init_role_templates`，读取 `reports/data/definitions/roles.yaml`
- 备选：`python manage.py init_standard_templates`，读取 Python 内置模板

两者都会写入 `RoleTemplate`，后执行的命令会覆盖同角色默认模板。生产环境建议只选择一种长期维护。

更多初始化数据说明见 [INIT_DATA_GUIDE_CN.md](INIT_DATA_GUIDE_CN.md)。

---

## 6. 发布前检查

本仓库提供三类检查脚本。

质量门禁：

```bash
PYTHON_BIN=venv/bin/python bash scripts/quality_gate.sh
```

安全扫描：

```bash
PYTHON_BIN=venv/bin/python bash scripts/security_scan.sh
```

部署检查：

```bash
PYTHON_BIN=venv/bin/python bash scripts/deploy_check.sh
```

检查内容：

- `pip check` 依赖一致性
- `manage.py check` 与 `check --deploy`
- 迁移漂移：`makemigrations --check --dry-run`
- OpenAPI 合约校验：`validate_api_contract`
- 全量测试集
- Bandit 静态安全扫描
- `pip-audit` 依赖漏洞扫描
- `collectstatic --dry-run`
- `runtime_maintenance`

发布前必须处理的高风险项：

- `DEBUG=False`
- 强随机 `DJANGO_SECRET_KEY`
- HTTPS、Secure Cookie、HSTS 配置正确
- `FIELD_ENCRYPTION_KEYS` 已配置
- 超级管理员 MFA 已启用
- 生产数据库不是 SQLite
- Redis/Celery 不指向开发机临时实例
- `/metrics` 已配置令牌保护
- 邮件发送、通知 Outbox、Celery Worker/Beat 正常
- 备份可校验且可在隔离环境恢复

---

## 7. 进程管理示例

### 7.1 Supervisor

创建 `/etc/supervisor/conf.d/workreport.conf`：

```ini
[program:workreport_web]
command=/var/www/workreport/venv/bin/daphne -b 127.0.0.1 -p 8000 workreport.asgi:application
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport/web.log
environment=DJANGO_SETTINGS_MODULE="settings"

[program:workreport_worker]
command=/var/www/workreport/venv/bin/celery -A celery_app worker -l info -Q default,exports,email,notifications
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport/worker.log
environment=DJANGO_SETTINGS_MODULE="settings"

[program:workreport_beat]
command=/var/www/workreport/venv/bin/celery -A celery_app beat -l info
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport/beat.log
environment=DJANGO_SETTINGS_MODULE="settings"
```

启动：

```bash
sudo mkdir -p /var/log/workreport
sudo chown -R www-data:www-data /var/log/workreport /var/www/workreport/media /var/www/workreport/backups
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status
```

### 7.2 systemd

如果使用 systemd，至少需要拆成 `workreport-web.service`、`workreport-worker.service`、`workreport-beat.service` 三个服务。发布时先停止 Beat，再滚动重启 Worker 与 Web，避免定时任务在迁移窗口重复触发。

---

## 8. Nginx 配置

非容器部署示例：

```nginx
upstream workreport_server {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name workreport.example.com;

    client_max_body_size 64m;

    location /static/ {
        alias /var/www/workreport/collected_static/;
        access_log off;
        expires 30d;
    }

    location /media/avatars/ {
        alias /var/www/workreport/media/avatars/;
        access_log off;
        expires 7d;
    }

    location /media/ {
        return 404;
    }

    location / {
        proxy_pass http://workreport_server;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

启用：

```bash
sudo ln -s /etc/nginx/sites-available/workreport /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

HTTPS 证书建议由负载均衡器或 Certbot 管理。只在 HTTPS 已稳定后启用 HSTS preload。

---

## 9. Docker Compose 部署

仓库提供 `Dockerfile`、`docker-compose.yml`、`docker/entrypoint.sh`、`docker/nginx.conf`、`docker/gunicorn.conf.py`。

当前 Compose 包含：

- `postgres`：PostgreSQL 16
- `redis`：Redis 7
- `web`：Daphne
- `worker`：Celery Worker
- `beat`：Celery Beat
- `nginx`：反向代理与静态文件

启动流程：

```bash
cp .env.example .env
# 修改 .env 中的 DJANGO_SECRET_KEY、FIELD_ENCRYPTION_KEYS、METRICS_TOKEN、POSTGRES_PASSWORD 等
# 确认镜像依赖中已包含 PostgreSQL 驱动，例如 psycopg[binary]
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
docker compose run --rm web python manage.py init_project_phases
docker compose run --rm web python manage.py init_rbac
docker compose run --rm web python manage.py init_role_templates
docker compose run --rm web python manage.py rebuild_search_index
docker compose up -d
```

默认端口：

```bash
HTTP_PORT=8080
```

入口脚本支持：

- `RUN_COLLECTSTATIC_ON_STARTUP=1`：启动时收集静态文件，默认开启
- `RUN_MIGRATIONS_ON_STARTUP=1`：启动时自动迁移，默认关闭
- `RUN_SEARCH_REBUILD_ON_STARTUP=1`：启动时重建搜索索引，默认关闭

生产环境建议把迁移、索引重建放在发布流水线中显式执行，不依赖容器启动自动执行。

---

## 10. 发布流程

推荐发布顺序：

```bash
cd /var/www/workreport
git pull
source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install "psycopg[binary]"

python manage.py backup_system --include-media --retention-days 30
python manage.py verify_backup /var/www/workreport/backups/最近一次备份目录

PYTHON_BIN=venv/bin/python bash scripts/quality_gate.sh
PYTHON_BIN=venv/bin/python bash scripts/security_scan.sh
PYTHON_BIN=venv/bin/python bash scripts/deploy_check.sh

python manage.py migrate
python manage.py rebuild_search_index
python manage.py collectstatic --noinput
python manage.py runtime_maintenance

sudo supervisorctl restart workreport_web
sudo supervisorctl restart workreport_worker
sudo supervisorctl restart workreport_beat
```

发布后验收：

```bash
curl -fsS https://workreport.example.com/healthz
curl -fsS https://workreport.example.com/readyz
curl -fsS -H "Authorization: Bearer <METRICS_TOKEN>" https://workreport.example.com/metrics
BASE_URL=https://workreport.example.com bash scripts/e2e_smoke.sh
```

人工冒烟清单：

- 登录、退出、注册邀请码
- 超级管理员首次登录 MFA 设置与恢复码保存
- 个人中心：头像、邮箱验证、通知偏好
- 项目：列表、详情、阶段变更、仓库、附件、成员
- 任务：创建、状态流转、评论、附件、导出
- 日报：新建、草稿、提交、我的日报、团队日报
- 团队管理：角色更新、项目添加/移除、权限校验
- 人事管理：薪资、合同、收款二维码，仅超级管理员可访问
- 通知：站内通知、WebSocket 推送、邮件 Outbox 重试
- 搜索：项目、任务、日报跨域搜索
- 审计：关键操作有日志，可筛选和导出

---

## 11. 备份与恢复

创建备份：

```bash
python manage.py backup_system --include-media --retention-days 30
```

校验备份：

```bash
python manage.py verify_backup /var/www/workreport/backups/workreport-YYYYMMDDTHHMMSSZ
```

恢复备份：

```bash
python manage.py restore_system /var/www/workreport/backups/workreport-YYYYMMDDTHHMMSSZ \
  --confirm=RESTORE-WORKREPORT --restore-media
```

恢复命令会覆盖当前数据库，只能在隔离环境或维护窗口执行。建议每日备份、异地复制、对象存储版本控制、季度恢复演练，并记录 RPO/RTO。

---

## 12. 日常运维

常用命令：

```bash
python manage.py check_task_sla
python manage.py send_report_reminders
python manage.py runtime_maintenance
python manage.py cleanup_logs
python manage.py archive_audit_logs
python manage.py audit_quality_check
python manage.py validate_templates
python manage.py verify_data_quality
python manage.py send_test_email --to user@example.com
```

Celery Beat 已配置：

- 每分钟分发通知 Outbox
- 每天 03:00 清理旧日志
- 每小时执行运行时维护

排障入口：

- 应用日志：关注 `request_id`、`workreport.request`、Sentry 事件 ID
- HTTP 头：`X-Request-ID`
- 就绪状态：`/readyz`
- 队列堆积：Celery Worker 日志与 Redis 指标
- 导出失败：`ExportJob.message` 与 `runtime_maintenance`
- 附件失败：存储凭证、对象存储签名、业务文件鉴权接口

---

## 13. 回滚原则

优先级：

1. 代码回滚到上一稳定提交并重启服务。
2. 如果迁移只新增字段/表，通常无需数据库回滚。
3. 如果迁移修改或删除数据，必须使用发布前备份在维护窗口恢复。
4. 回滚后执行 `/readyz`、登录、核心业务冒烟和 Celery 队列检查。

禁止在不了解数据状态时直接删除迁移、强制重置数据库或覆盖生产媒体目录。
