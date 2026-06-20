# WorkReport 系统部署方案与步骤

本文档详细说明了如何在 Linux 服务器上部署 WorkReport 系统。

---

## 1. 环境要求 (Prerequisites)

- **操作系统**: Ubuntu 20.04+ / CentOS 8+ / Debian 10+
- **Python**: 3.10 或更高版本
- **数据库**: MySQL 8.0+ 或 PostgreSQL 13+ (推荐 PostgreSQL)
- **缓存/消息队列**: Redis 6.0+
- **Web 服务器**: Nginx
- **进程管理**: Supervisor 或 Systemd

---

## 2. 基础环境安装

```bash
# Ubuntu/Debian 示例
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev libmysqlclient-dev libpq-dev redis-server nginx git

# 启动 Redis
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

---

## 3. 代码部署

### 3.1 克隆代码
```bash
cd /var/www
sudo git clone <repository_url> workreport
cd workreport
```

### 3.2 创建虚拟环境与安装依赖
```bash
python3 -m venv venv
source venv/bin/activate

# 升级 pip
pip install --upgrade pip

# 安装依赖
pip install -r requirements.txt

# 安装生产环境服务器
pip install gunicorn uvicorn[standard]
# 如果使用 MySQL
pip install mysqlclient
# 如果使用 PostgreSQL
pip install psycopg2-binary
```

---

## 4. 应用配置

### 4.1 环境变量配置
复制示例配置并修改：
```bash
cp .env.example .env
nano .env
```

**关键配置项**:
```ini
DJANGO_SECRET_KEY=请生成一个长随机字符串
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=your_domain.com,server_ip
DJANGO_CSRF_TRUSTED_ORIGINS=https://your_domain.com
DJANGO_TRUST_PROXY_HEADERS=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
MFA_REQUIRED_FOR_SUPERUSERS=True

# 生产环境必须显式配置数据库，禁止回退 SQLite
DJANGO_ALLOW_SQLITE_IN_PRODUCTION=False

# 数据库配置
DB_ENGINE=django.db.backends.mysql  # 或 django.db.backends.postgresql
DB_NAME=workreport
DB_USER=workreport_user
DB_PASSWORD=your_secure_password
DB_HOST=127.0.0.1
DB_PORT=3306 # PGSQL 使用 5432
DB_CONN_MAX_AGE=60
DB_ATOMIC_REQUESTS=False

# Redis 配置 (Celery & Cache)
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
CHANNEL_LAYER_BACKEND=redis
CHANNEL_REDIS_URL=redis://127.0.0.1:6379/1
CACHE_BACKEND=redis
CACHE_REDIS_URL=redis://127.0.0.1:6379/2

# 可观测性
LOG_FORMAT=json
LOG_LEVEL=INFO
METRICS_TOKEN=请生成独立随机令牌
SENTRY_DSN=https://examplePublicKey@o0.ingest.sentry.io/0
SENTRY_ENVIRONMENT=production
APP_RELEASE=git-commit-sha

# 邮件配置 (SMTP) - 用于发送通知
EMAIL_HOST=smtp.exmail.qq.com
EMAIL_PORT=465
EMAIL_HOST_USER=your_email@domain.com
EMAIL_HOST_PASSWORD=your_email_password
EMAIL_USE_SSL=True
DEFAULT_FROM_EMAIL=your_email@domain.com

# 通知 Outbox
NOTIFICATION_OUTBOX_SYNC=False
NOTIFICATION_OUTBOX_MAX_ATTEMPTS=8

# Celery 任务治理
CELERY_TASK_ACKS_LATE=True
CELERY_TASK_REJECT_ON_WORKER_LOST=True
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_WORKER_MAX_TASKS_PER_CHILD=200
CELERY_TASK_SOFT_TIME_LIMIT=300
CELERY_TASK_TIME_LIMIT=360
CELERY_EXPORT_QUEUE=exports
CELERY_EMAIL_QUEUE=email
CELERY_NOTIFICATION_QUEUE=notifications
EXPORT_JOB_STALE_MINUTES=60
UPLOAD_SESSION_TTL_HOURS=24
```

### 4.2 敏感数据密钥与 MFA

生产环境必须配置 `FIELD_ENCRYPTION_KEYS`。使用以下命令生成 Fernet 密钥：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```ini
FIELD_ENCRYPTION_KEYS=当前主密钥
OTP_TOTP_ISSUER=WorkReport
MFA_REQUIRED_FOR_SUPERUSERS=True
```

密钥轮换时将新密钥放在第一位、旧密钥保留在后，例如 `新密钥,旧密钥`。完成数据重加密和备份验证前不可删除旧密钥。超级管理员首次登录会进入 TOTP 设置页，恢复码只显示一次，应存入组织密码管理器。

### 4.3 附件对象存储（可选）

系统支持私有 Amazon S3 兼容存储和阿里云 OSS，下载地址使用短期签名 URL。凭证应通过实例角色、密钥管理服务或环境变量注入，不要写入代码仓库。

```ini
# S3 / MinIO / 其他 S3 兼容服务
S3_BUCKET=workreport-prod
S3_REGION=ap-southeast-1
S3_ENDPOINT_URL=
S3_ADDRESSING_STYLE=auto
S3_SERVER_SIDE_ENCRYPTION=AES256
S3_URL_EXPIRY=300
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=

# 阿里云 OSS
OSS_BUCKET=workreport-prod
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
OSS_URL_EXPIRY=300
```

通过系统设置 `attachment_storage_config` 将 `task_attachment` 或 `project_attachment` 策略切换到 `s3` / `oss`。首次切换应在预发布环境验证上传、签名下载、删除、重复文件名和旧附件回读。

如需启用浏览器直传对象存储：

```ini
DIRECT_UPLOAD_ENABLED=True
DIRECT_UPLOAD_EXPIRES_SECONDS=900
```

直传只应在默认附件后端为 `s3` 或 `oss` 时开启。流程为：前端调用 `/accounts/api/upload/direct/init/` 获取预签名参数，浏览器直传对象存储，再调用 `/accounts/api/upload/direct/complete/` 校验对象大小，最后由项目/任务附件接口绑定业务记录。对象存储侧建议启用版本控制、服务端加密、未完成分片清理和过期临时对象生命周期策略。

### 4.4 初始化系统
```bash
# 数据库迁移
python manage.py migrate

# 重建跨域搜索索引（首次上线 P1 或大批量导入后执行）
python manage.py rebuild_search_index

# 收集静态文件
python manage.py collectstatic --noinput

# 创建管理员账号
python manage.py createsuperuser

# 初始化基础数据（建议）
python manage.py init_project_phases
python manage.py init_rbac

# 初始化模板（二选一，选定一种长期维护）
# 方案 A（推荐：YAML 可配置）
python manage.py init_role_templates
# 方案 B（内置默认：Python 常量）
# python manage.py init_standard_templates
```

### 4.5 健康检查与指标

- `GET /healthz`：进程存活检查，不访问外部依赖。
- `GET /readyz`：数据库与缓存就绪检查；失败返回 HTTP 503。
- `GET /metrics`：Prometheus 指标，生产环境必须携带 `Authorization: Bearer <METRICS_TOKEN>`。

负载均衡器应使用 `/readyz` 决定是否接收流量。日志使用 JSON 输出并包含 `request_id`，响应头 `X-Request-ID` 可用于关联用户反馈、应用日志和 Sentry 事件。

### 4.6 备份、校验与恢复演练

```bash
# 每日原生数据库备份，可选同时归档本地媒体
python manage.py backup_system --include-media --retention-days 30

# 校验文件大小与 SHA-256
python manage.py verify_backup /backup/workreport-YYYYMMDDTHHMMSSZ

# 仅在隔离环境或维护窗口执行；该命令会覆盖当前数据库
python manage.py restore_system /backup/workreport-YYYYMMDDTHHMMSSZ \
  --confirm=RESTORE-WORKREPORT --restore-media
```

PostgreSQL 需要安装 `pg_dump/pg_restore`，MySQL 需要安装 `mysqldump/mysql`。建议每日自动备份、异地复制、季度隔离恢复演练，并记录 RPO/RTO。对象存储应另外启用版本控制和生命周期策略。

### 4.7 发布前检查、搜索索引与运行时维护

```bash
python manage.py check --deploy
python manage.py migrate --check
python manage.py collectstatic --noinput --dry-run
python manage.py runtime_maintenance
```

`runtime_maintenance` 会清理过期上传会话、过期导出文件，并标记长时间卡在 `running` 的导出任务。线上应由 Celery Beat 每小时自动执行；手工发布前执行一次可以提前暴露文件权限和配置问题。

搜索优先使用 `SearchIndex` 表；PostgreSQL 会在迁移时自动创建全文 GIN 索引和 trigram 索引。迁移后执行 `rebuild_search_index` 完成历史数据回填，日常新增/修改由模型信号增量同步。若索引尚未回填，搜索服务会回退到旧查询逻辑，避免发布窗口内搜索完全不可用。

### 4.8 容器化部署

仓库提供 `Dockerfile`、`docker-compose.yml`、`docker/nginx.conf` 和 `docker/entrypoint.sh`。最小启动流程：

```bash
cp .env.example .env
# 修改 .env 中的 DJANGO_SECRET_KEY、FIELD_ENCRYPTION_KEYS、METRICS_TOKEN、POSTGRES_PASSWORD 等
docker compose build
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py rebuild_search_index
docker compose up -d
```

容器默认使用 Daphne 承载 HTTP 和 WebSocket。`web`、`worker`、`beat` 分离运行，Worker 监听 `default,exports,email,notifications` 队列。生产环境不建议依赖容器启动自动迁移；如确需在受控环境启用，可设置 `RUN_MIGRATIONS_ON_STARTUP=1`。

更多初始化数据说明请参考：[INIT_DATA_GUIDE_CN.md](file:///Users/lingchong/Downloads/wwwroot/workreport/docs/INIT_DATA_GUIDE_CN.md)

---

## 5. 服务启动配置 (Supervisor 方案)

推荐使用 Supervisor 管理 Django 应用、Celery Worker 和 Celery Beat 进程。

### 安装 Supervisor
```bash
sudo apt install supervisor
```

### 配置文件
创建 `/etc/supervisor/conf.d/workreport.conf`:

```ini
[program:workreport_web]
command=/var/www/workreport/venv/bin/daphne -b 127.0.0.1 -p 8000 workreport.asgi:application
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport_web.log

[program:workreport_celery_worker]
command=/var/www/workreport/venv/bin/celery -A celery_app worker -l info -Q default,exports,email,notifications
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport_worker.log

[program:workreport_celery_beat]
command=/var/www/workreport/venv/bin/celery -A celery_app beat -l info
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport_beat.log
```

*注意：使用 Daphne 以支持 Django Channels (WebSocket)。如仅部署纯 WSGI HTTP，可改用 `gunicorn -c docker/gunicorn.conf.py wsgi:application`。*

### 启动服务
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status
```

---

## 6. Nginx 反向代理配置

创建 `/etc/nginx/sites-available/workreport`:

```nginx
upstream workreport_server {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name your_domain.com;

    client_max_body_size 50M; # 允许大文件上传

    location /static/ {
        alias /var/www/workreport/staticfiles/;
    }

    # 仅头像允许公开访问；合同、项目/任务附件和收款码由 Django 鉴权后返回。
    location /media/avatars/ {
        alias /var/www/workreport/media/avatars/;
    }

    location / {
        proxy_pass http://workreport_server;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

启用站点并重启 Nginx:
```bash
sudo ln -s /etc/nginx/sites-available/workreport /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 7. 维护与监控

### 查看日志
- Web 访问日志: `/var/log/nginx/access.log`
- 应用错误日志: `/var/log/workreport_web.log`
- Celery 日志: `/var/log/workreport_worker.log`

### 代码更新
```bash
cd /var/www/workreport
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo supervisorctl restart workreport_web
sudo supervisorctl restart workreport_celery_worker
```

### 备份
建议定期备份数据库和 `media` 目录。
