# TM 团队日报与任务平台

面向团队的日报、任务、项目管理与账户安全中心。下文覆盖功能说明、使用方法与部署指南。

## 1. 功能说明

- **用户认证与个人中心**
  - 注册/登录/退出，带密码强度策略（可配置）、用户名唯一性校验。
  - 个人中心可修改用户名、密码（校验原密码 + 强度评分）与邮箱；邮箱验证含冷却与倒计时提示。
  - 邮箱绑定后提示可用于找回密码（需配置邮件服务）。
- **日报管理**
  - 填写日报、查看我的日报、导出 CSV，支持角色、日期、项目、状态过滤。
  - 连续提交天数（streak）与今日提交状态提示。
  - 管理员可查看/过滤全员日报并导出。
- **任务管理**
  - “我的任务”列表筛选（状态/项目/关键词）、逾期/紧急标记，支持批量导出。
  - 管理端任务创建、分配、批量操作与统计。
  - SLA 提醒窗口（小时）可按项目或全局配置。
- **项目管理**
  - 项目列表、创建、编辑、删除，成员/管理员分配，项目级 SLA。
- **角色模板与搜索**
  - 日报角色模板管理（提示语、占位符、示例 Markdown）。
  - 项目、用户远程搜索接口（管理员权限）。
- **审计与统计**
  - 审计日志、项目/日报统计看板。
- **UI/UX**
  - 顶部导航、闪存消息、动画化按钮与响应式布局，符合 Space Grotesk + Noto Sans SC 的视觉风格。
- **性能与模板**
  - 统计/绩效看板默认缓存约 10 分钟，可在数据变更后等待或刷新。
  - 多级 SLA 阈值（红/黄）可在 SLA 配置页设置，任务列表与看板显示当前阈值。
  - 模板中心支持关键词/角色/项目筛选，分页浏览，套用模板时按“项目→角色→全局”优先级自动回退。

## 2. 使用说明

### 安装步骤
1. 克隆代码并进入目录：
   ```bash
   git clone <repo-url> workreport
   cd workreport
   ```
2. 创建虚拟环境并安装依赖（示例使用 Django 4.2.x）：
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install "django>=4.2,<5.0"
   ```
   如果已有 `requirements.txt`，请执行 `pip install -r requirements.txt`。
3. 初始化数据库：
   ```bash
   python manage.py migrate
   python manage.py createsuperuser  # 创建管理员账号
   ```
4. 启动开发服务器：
   ```bash
   python manage.py runserver
   ```
5. 访问：
   - 登录页：`/accounts/login/`
   - 注册页：`/accounts/register/`
   - 个人中心：`/accounts/settings/`
   - 工作台：`/reports/workbench/`

### 配置参数说明
- **安全与密码**
  - `PASSWORD_MIN_SCORE`（可选）：密码最小评分，默认 3（满分 6：8/12 长度、大写、小写、数字、符号）。
- **邮件通知（用于邮箱验证/找回密码）**
  - `EMAIL_BACKEND`：默认 `django.core.mail.backends.console.EmailBackend`（控制台打印）。
  - `EMAIL_HOST` / `EMAIL_PORT`：SMTP 主机与端口（465 常用 SSL，587 常用 TLS）。
  - `EMAIL_USE_SSL` / `EMAIL_USE_TLS`：安全传输开关（互斥，留空则按端口自动选择）。
  - `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD`：发信账号与授权码。
  - `DEFAULT_FROM_EMAIL`：默认发件人，未设置时回退到 `EMAIL_HOST_USER` 或 `no-reply@example.com`。
- **其他**
  - `DEBUG`、`ALLOWED_HOSTS`、`SECRET_KEY`：部署时需设置安全值。
  - `SLA_REMIND_HOURS`：全局 SLA 提醒窗口（小时）。
  - 数据库默认 SQLite，可改为 Postgres/MySQL。

### 典型使用示例
- **新成员注册并填写日报**
  1. 访问 `/accounts/register/` 注册，参考密码强度提示完成设置。
  2. 登录后进入 `/reports/workbench/`，点击“填写日报”并提交。
  3. 在“我的日报”查看、筛选或导出 CSV。
- **管理员创建项目与任务**
  1. 登录管理员账号，进入“项目列表”创建项目并设置 SLA 小时数。
  2. 在“任务管理”创建/分配任务，使用筛选查看紧急任务（依据 SLA）。
- **绑定邮箱并验证**
  1. 打开 `/accounts/settings/`，输入邮箱发送验证码（带冷却倒计时）。
  2. 输入验证码完成绑定，后续可用于通知/找回密码。

### 常见问题解决
- **无法发送邮件**：检查 SMTP 配置是否正确；开发环境可先使用 console backend；确认 TLS/SSL 未同时开启。
- **密码总被拒绝**：查看页面“强度评分”提示，满足长度、大小写、数字、符号至少 `PASSWORD_MIN_SCORE` 项。
- **用户名提示被占用**：系统实时检测唯一性，需换一个未使用的用户名。
- **静态资源 404（部署）**：确保执行 `python manage.py collectstatic` 并由 Nginx/容器正确挂载 `staticfiles/`。

## 3. 部署指南

### 系统环境要求
- Python 3.10+（建议）
- pip / virtualenv
- 数据库：默认 SQLite；生产建议 Postgres/MySQL。
- 可选：Redis/缓存（用于未来扩展限流或会话存储）。

### 依赖安装
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install "django>=4.2,<5.0"
```
（如有额外依赖，请使用 `pip install -r requirements.txt`）

### 部署流程
1. 设置环境变量：
   ```bash
   export DEBUG=False
   export SECRET_KEY='请替换为强随机值'
   export ALLOWED_HOSTS='your.domain.com'
   # 邮件发送配置（如需）
   export EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
   export EMAIL_HOST=smtp.example.com
   export EMAIL_PORT=465
   export EMAIL_USE_SSL=true
   export EMAIL_HOST_USER=...
   export EMAIL_HOST_PASSWORD=...
   ```
2. 数据库迁移与静态资源：
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```
3. 创建管理员：
   ```bash
   python manage.py createsuperuser
   ```
4. 运行应用（示例 gunicorn）：
   ```bash
   gunicorn wsgi:application --bind 0.0.0.0:8000 --workers 3
   ```
5. 前置 Nginx/反向代理：转发 80/443 到 Gunicorn；提供静态资源目录 `staticfiles/`。

### 性能与安全建议
- 关闭 `DEBUG`，设置合理的 `ALLOWED_HOSTS`、强随机 `SECRET_KEY`。
- 使用持久数据库（Postgres/MySQL）并配置连接池。
- 考虑接入缓存（Redis/Memcached）以减少数据库读取压力。
- 为邮箱验证码等接口加入更强的限流/黑名单（当前为会话冷却，可扩展为 IP + 频次策略）。
- 开启 HTTPS，前置 WAF/反爬策略，定期审计管理员操作。
- 定期 `collectstatic` 并通过 CDN/Nginx 进行静态资源缓存。

---

如需更多信息或自定义扩展，请查阅 `settings.py` 和 `reports/` 目录内的视图与表单实现。***
