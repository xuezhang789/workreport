# TM 团队日报与任务平台 / TM Team Daily & Task Platform

## 1. 项目功能架构 / Functional Architecture
- **总体 / Overall**：基于 Django 的团队日报 + 任务 + 项目 + 账户安全平台，包含前台工作台与后台管理。
- **主要模块 / Main Modules**
  - 账户与安全 / Accounts & Security：注册、登录、登出、个人中心（用户名/密码/邮箱绑定与验证码冷却），权限判断（管理员/项目管理员/普通用户），友好 403 页面。
  - 日报 / Daily Reports：填写、我的日报筛选与导出、管理员全员日报筛选与导出、角色模板、缺报统计与催报。
  - 任务 / Tasks：我的任务（状态/项目/关键词/紧急筛选、批量操作、导出），管理员任务创建/分配/批量操作/导出/统计，SLA 阈值与剩余时间标记。
  - 项目 / Projects：创建/编辑/删除（软禁用）、成员与管理员分配、项目级 SLA。
  - 模板中心 / Template Center：日报与任务模板的版本化存储，按项目→角色→全局优先级套用，支持搜索/筛选/排序/分页。
  - 统计与绩效 / Stats & Performance：日报缺报统计、项目 SLA 达成、逾期任务榜单；绩效看板（项目/角色完成率、逾期率、连签趋势），缓存约 10 分钟，可刷新。
  - 审计 / Audit：访问、导出、更新等操作日志查询与导出。
- **数据模型 / Data Models（reports/models.py）**
  - Profile（角色）
  - Project、ReminderRule、ReportMiss、DailyReport、RoleTemplate
  - Task、TaskComment、TaskAttachment、TaskSlaTimer、TaskHistory、TaskTemplateVersion
  - ReportTemplateVersion、SystemSetting、AuditLog
- **路由 / URLs**
  - 根：`urls.py`；业务：`reports/urls.py`（workbench、reports、tasks、projects、stats、performance、templates、audit 等）。

## 2. 核心模块技术实现 / Technical Implementation
- **权限 / Permissions**
  - `has_manage_permission` 允许 staff 或特定角色；项目级 `has_project_manage_permission` 控制项目/任务操作。
  - 友好 403：`_admin_forbidden` 渲染 `templates/403.html`。
- **SLA 逻辑 / SLA Logic**
  - 全局阈值：settings 中默认 `SLA_TIGHT_HOURS_DEFAULT=6`、`SLA_CRITICAL_HOURS_DEFAULT=2`，可在 `SystemSetting` 写入 `sla_thresholds`（amber/red）与 `sla_hours`。
  - `_calc_sla_info` 计算截止/剩余/级别（green/amber/red）并附带排序值；列表展示当前阈值。
- **缓存策略 / Caching**
  - 绩效看板 `_performance_stats`、统计页 `stats` 结果缓存约 10 分钟，返回生成时间 `generated_at`；可手动刷新按钮。
  - 缓存失效：Task/DailyReport 保存/删除、批量操作、项目编辑、角色模板/模板保存等触发 `_invalidate_stats_cache()`。
- **模板套用 / Template Application**
  - `template_apply_api`：按 type=report|task，优先匹配 项目→角色→全局，回退时返回 `fallback` 标记。
  - 前端按钮支持输入模板名、传多项目 ID，未命中时提示清空筛选或用全局。
- **导出限制 / Export Limit**
  - 全局 `MAX_EXPORT_ROWS=5000`；超过返回 400，前端提示“数据量过大，请缩小筛选范围”。
- **SLA 配置 / SLA Settings**
  - `templates/reports/sla_settings.html` 支持提醒窗口与红/黄阈值输入，存入 `SystemSetting`。
- **审计与日志 / Audit**
  - `log_action` 记录用户、路径、方法、IP、UA 等；关键操作（导出/更新/删除）均调用。
- **测试 / Tests（tests/test_sla_and_templates.py）**
  - 覆盖 SLA 配置写入、模板回退、缓存失效、权限 403、导出限额提示、模板分页、SLA 阈值显示。

## 3. 安装部署指南 / Installation & Deployment
- **环境要求 / Requirements**
  - Python 3.10+，pip，virtualenv；Django 4.2+；数据库默认 SQLite（可改 Postgres/MySQL）。
- **本地安装 / Local Setup**
  1) 克隆并进入目录  
     ```bash
     git clone <repo-url> workreport
     cd workreport
     ```
  2) 创建虚拟环境 & 安装依赖  
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     pip install "django>=4.2,<5.0"
     ```  
     如有 `requirements.txt`：`pip install -r requirements.txt`
  3) 初始化数据库  
     ```bash
     python manage.py migrate
     python manage.py createsuperuser
     ```
  4) 启动开发服务器  
     ```bash
     python manage.py runserver
     ```
  5) 访问入口  
     - 登录 `/accounts/login/`
     - 注册 `/accounts/register/`
     - 工作台 `/reports/workbench/`
- **配置 / Configuration**
  - 基础：`DEBUG`、`SECRET_KEY`、`ALLOWED_HOSTS`
  - 邮件：`EMAIL_BACKEND`、`EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_USE_SSL`/`EMAIL_USE_TLS`、`EMAIL_HOST_USER`、`EMAIL_HOST_PASSWORD`、`DEFAULT_FROM_EMAIL`
  - 安全：`PASSWORD_MIN_SCORE`
  - SLA：`SLA_TIGHT_HOURS_DEFAULT`、`SLA_CRITICAL_HOURS_DEFAULT`；管理页设置 `sla_hours`、`sla_thresholds`
- **生产部署示例 / Production Example**
  ```bash
  export DEBUG=False
  export SECRET_KEY='strong-random'
  export ALLOWED_HOSTS='your.domain.com'
  # 配置邮件与数据库...
  python manage.py migrate
  python manage.py collectstatic --noinput
  gunicorn wsgi:application --bind 0.0.0.0:8000 --workers 3
  ```
  前置 Nginx/反向代理，挂载 `staticfiles/`，使用 HTTPS。

## 4. 使用操作与示例 / Usage & Examples
- **账户与安全 / Accounts**
  - 个人中心 `/accounts/settings/`：修改用户名/密码/邮箱；邮箱验证码有冷却，生产环境不回显验证码。
- **日报 / Reports**
  - 填写 `/reports/new/`：选择角色/日期/项目（可多选）；“套用模板”按项目→角色→全局回退。
  - 我的日报 `/reports/my/`：按日期/状态/项目/角色/关键词筛选；导出 CSV（超限提示）。
  - 管理员日报 `/reports/admin/reports/`：筛选全员日报并导出；权限不足显示友好 403。
- **任务 / Tasks**
  - 我的任务 `/reports/tasks/`：筛选状态/项目/关键词/紧急；批量完成/重开/导出；显示 SLA 阈值和剩余时间。
  - 管理任务 `/reports/tasks/admin/`：创建/分配、批量操作（完成/重开/逾期）、导出/统计；权限不足提示友好。
- **项目 / Projects**
  - `/reports/projects/`：查看/筛选；创建、编辑（自动清缓存）、软删除；导出需先过滤。
- **模板中心 / Template Center**
  - `/reports/templates/center/`：创建日报/任务模板（版本记录），搜索筛选（关键词/角色/项目），排序（版本/更新时间），分页与跳页；套用支持回退并有提示。
- **统计与绩效 / Stats & Performance**
  - `/reports/stats/`：日报缺报列表、项目 SLA 达成、逾期 Top；缓存约 10 分钟，显示最后刷新时间，可刷新；导出前提示过滤。
  - `/reports/performance/`：项目/角色完成率、逾期率、连签趋势，显示 SLA 阈值，缓存约 10 分钟，支持刷新与导出，并提示导出过滤。
- **审计 / Audit**
  - `/reports/audit/`：筛选审计日志并导出；权限不足显示友好 403。

### 关键参数 / Key Parameters
- **模板套用 API**：`type=report|task`，可传 `role`、`project`（多值）、`name`；返回 `fallback` 表示使用角色/全局模板。
- **SLA 配置**：`sla_hours`（提醒窗口小时数），`sla_amber`、`sla_red`（阈值小时数），存于 SystemSetting。
- **导出限额**：`MAX_EXPORT_ROWS=5000`，超出返回 400，前端提示缩小过滤范围。
