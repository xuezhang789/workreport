# WorkReport 使用与部署指南

本文档涵盖使用指南、部署方法、宝塔面板定时任务配置，以及邮件服务配置与测试方式。请按章节逐步操作。

## 1. 使用指南

### 1.1 登录与角色
- 访问 `/accounts/login/` 登录；管理员或项目管理角色（mgr/pm）可进入管理入口。
- 普通成员可访问：我的日报、我的任务、项目列表。

### 1.2 日报与任务
- 填写日报：`日报 -> 填写日报 / New Report`，提交后可在“我的日报”查看。
- 我的任务：
  1) 过滤：按状态/项目/关键词或“仅看紧张/逾期”筛选。
  2) 批量操作：勾选任务 → 选择批量操作（完成/重新打开/批量更新状态或截止时间）→ 确认提示后提交。
  3) 导出：列表右上角“导出”按钮。
- 任务管理（管理员/项目管理员）：
  1) 列表支持按项目/用户筛选，“批量更新”可同时修改状态/截止/负责人（可按角色过滤负责人）。
  2) 发布新任务：`任务管理 / Tasks Admin -> 发布新任务`，选择项目、负责人、截止时间并提交。

### 1.3 项目管理
- 新建/编辑项目：`项目列表 / Projects -> 新建`，填写名称/代码/SLA/负责人/成员/管理员。成员与管理员为多选。
- 项目成员角色调整（建议改造点）：项目详情页可扩展角色切换/移除并记录审计。

### 1.4 统计与看板
- 绩效看板、统计看板：仅管理员可见。
- 任务统计：管理员或项目管理员可查看/导出；可按项目、用户过滤。

## 2. 部署方法

### 2.1 环境要求
- Python 3.10+（建议 3.11/3.12）
- SQLite 默认即可；如需生产数据库，请配置 `DATABASES`。
- 推荐使用虚拟环境（venv）。

### 2.2 安装依赖
```bash
# 克隆代码后
cd /path/to/workreport
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.3 初始化与运行
```bash
# 如需迁移数据库（默认 sqlite）
python manage.py migrate

# 创建管理员账号
python manage.py createsuperuser

# 本地运行
python manage.py runserver 0.0.0.0:8000
```

### 2.4 配置项（settings.py 要点）
- `DEBUG=False` 时请配置 `ALLOWED_HOSTS`。
- 静态文件：`STATIC_URL=/static/`，生产环境请收集静态资源并由 Web 服务器托管。
- 邮件配置：见第 4 节。

## 3. 宝塔面板定时任务设置示例

> 假设项目路径 `/www/wwwroot/workreport`，虚拟环境 `/www/wwwroot/workreport/.venv/`。

### 3.1 任务：SLA/截止扫描与提醒
- 类型：Shell 脚本
- 脚本内容：
```bash
cd /www/wwwroot/workreport && /www/wwwroot/workreport/.venv/bin/python manage.py check_task_sla
```
- 触发：每 10 分钟执行一次（可按需调整）。
- 注意：需保证 SMTP 已配置，避免提醒发送失败。

### 3.2 任务：日报缺报提醒
- 类型：Shell 脚本
- 脚本内容：
```bash
cd /www/wwwroot/workreport && /www/wwwroot/workreport/.venv/bin/python manage.py send_report_reminders
```
- 触发：每天 20:10（或规则设置的截止时间后）执行，工作日建议生效。

### 3.3 定时任务通用参数
- 执行用户：建议 www 或项目所属用户。
- 日志：开启“保存执行日志”，便于排查。
- 环境：如有多 Python 版本，请确认命令中 Python 路径与 venv 一致。

## 4. 邮箱服务配置说明

### 4.1 SMTP 关键配置（settings.py）
```python
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend' if DEBUG else 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))  # TLS 587 / SSL 465
EMAIL_USE_TLS = ...  # 与 EMAIL_USE_SSL 互斥，依据端口自动推断或显式指定
EMAIL_USE_SSL = ...
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER')  # 发信账号
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD')  # 授权码/密码
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or '')
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 10))
EMAIL_SUBJECT_PREFIX = os.environ.get('EMAIL_SUBJECT_PREFIX', '[WorkReport] ')
```
- 注意事项：
  - `EMAIL_USE_TLS` 与 `EMAIL_USE_SSL` 不能同时为 True。
  - 生产环境务必使用环境变量提供账号/密码，避免硬编码。
  - `DEBUG=True` 默认使用 console backend，防止误发。

### 4.2 环境变量示例（.env 或部署面板）
```bash
export EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
export EMAIL_HOST=smtp.gmail.com
export EMAIL_PORT=587
export EMAIL_USE_TLS=true
export EMAIL_USE_SSL=false
export EMAIL_HOST_USER="your_account@gmail.com"
export EMAIL_HOST_PASSWORD="your_app_password"  # 请使用授权码
export DEFAULT_FROM_EMAIL="WorkReport <your_account@gmail.com>"
```

### 4.3 测试邮件发送
使用内置管理命令：
```bash
cd /path/to/workreport
python manage.py send_test_email --to you@example.com --subject "SMTP test" --message "hello" --timeout 10
```
- 如需切换发件人或 backend：
```bash
python manage.py send_test_email --to you@example.com --from no-reply@example.com --backend django.core.mail.backends.smtp.EmailBackend --timeout 10
```
- 常见问题：
  - 认证失败：检查账号/授权码/发件人是否匹配。
  - 超时：确认端口（TLS 587 / SSL 465）与防火墙放行。
  - DNS 解析失败：检查 `EMAIL_HOST` 配置。

## 5. 常见操作步骤速查
- 创建管理员：`python manage.py createsuperuser`
- 迁移数据库：`python manage.py migrate`
- 收集静态资源（生产）：`python manage.py collectstatic`
- 运行提醒扫描（手动）：`python manage.py check_task_sla`
- 运行缺报提醒（手动）：`python manage.py send_report_reminders`

> 以上步骤与配置请结合实际服务器路径和账户权限调整。若使用反向代理/容器，请同步修改对应的工作目录与启动命令。***
