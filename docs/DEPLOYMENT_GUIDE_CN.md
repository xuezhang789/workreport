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

# 数据库配置
DB_ENGINE=django.db.backends.mysql  # 或 django.db.backends.postgresql
DB_NAME=workreport
DB_USER=workreport_user
DB_PASSWORD=your_secure_password
DB_HOST=127.0.0.1
DB_PORT=3306 # PGSQL 使用 5432

# Redis 配置 (Celery & Cache)
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0

# 邮件配置 (SMTP) - 用于发送通知
EMAIL_HOST=smtp.exmail.qq.com
EMAIL_PORT=465
EMAIL_HOST_USER=your_email@domain.com
EMAIL_HOST_PASSWORD=your_email_password
EMAIL_USE_SSL=True
DEFAULT_FROM_EMAIL=your_email@domain.com
```

### 4.2 初始化系统
```bash
# 数据库迁移
python manage.py migrate

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
command=/var/www/workreport/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000 workreport.asgi:application
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport_web.log

[program:workreport_celery_worker]
command=/var/www/workreport/venv/bin/celery -A workreport worker -l info
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport_worker.log

[program:workreport_celery_beat]
command=/var/www/workreport/venv/bin/celery -A workreport beat -l info
directory=/var/www/workreport
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/workreport_beat.log
```

*注意：使用了 `uvicorn` worker 以支持 Django Channels (WebSocket)。*

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

    location /media/ {
        alias /var/www/workreport/media/;
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
