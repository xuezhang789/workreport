# WorkReport 项目技术文档

## 1. 项目概述
**WorkReport** 是一个基于 Django 的企业级工时汇报与项目管理系统。它提供了日报管理、任务跟踪、项目协作、SLA 服务水平监控以及绩效统计等核心功能。系统采用前后端混合架构（Django Templates + HTMX + Vue.js/jQuery），支持多语言（中/英）和多角色（普通员工、经理、管理员）权限控制。

## 2. 系统架构

### 2.1 技术栈
- **后端框架**: Django 4.2+ (Python 3.9+)
- **数据库**: SQLite (开发) / MySQL (生产)
- **前端技术**: 
  - Django Templates (服务端渲染)
  - HTMX (局部刷新/AJAX)
  - CSS Variables (主题定制)
  - Vanilla JS (交互逻辑)
- **实时通信**: Django Channels (WebSocket) - 用于通知推送
- **任务队列**: 
  - 简单异步: `threading` (当前实现)
  - 扩展支持: Celery (架构预留)
- **缓存**: Django Cache (LocMemCache/Redis)

### 2.2 目录结构
```
workreport/
├── core/               # 核心模块 (用户, 认证, 通用工具)
├── tasks/              # 任务管理 (CRUD, SLA, 评论, 附件)
├── projects/           # 项目管理 (团队, 权限, 成员)
├── reports/            # 汇报与统计 (日报, 看板, 通知)
├── audit/              # 审计日志 (操作记录, 历史追踪)
├── work_logs/          # 日报模型定义
├── static/             # 静态资源 (CSS, JS, Images)
├── templates/          # HTML 模板
└── manage.py           # CLI 入口
```

## 3. 核心功能模块

### 3.1 核心模块 (Core)
- **职责**: 处理用户认证、个人资料 (`Profile`)、系统设置 (`SystemSetting`) 和通用权限控制。
- **关键组件**:
  - `Profile`: 扩展 User 模型，包含职位、部门、头像等信息。
  - `utils.py`: 提供 `_admin_forbidden`, `_validate_file` 等通用工具。
  - `permissions.py`: 定义 `has_manage_permission` 等权限判定逻辑。

### 3.2 任务管理 (Tasks)
- **职责**: 全生命周期的任务追踪。
- **特性**:
  - **SLA 监控**: 基于 `SystemSetting` 中的阈值计算任务剩余时间（正常/紧张/逾期）。
  - **状态机**: 定义任务状态流转规则 (Todo -> In Progress -> Review -> Done)。
  - **协作**: 支持 `@提及`、评论、附件上传。
  - **批量操作**: 批量完成、删除、指派、导出。
  - **HTMX 集成**: 任务列表支持无刷新筛选和分页。

### 3.3 项目管理 (Projects)
- **职责**: 项目维度的资源与权限隔离。
- **权限模型**:
  - **Owner**: 项目创建者，拥有最高权限。
  - **Manager**: 被指派的管理者，可编辑项目和管理任务。
  - **Member**: 普通成员，仅可见和编辑相关任务。
- **逻辑**: `get_accessible_projects(user)` 是权限过滤的核心函数。

### 3.4 汇报与统计 (Reports)
- **职责**: 个人日报提交与管理层绩效分析。
- **流程**:
  1. 用户每日提交 `DailyReport`。
  2. 系统自动计算“连签” (Streak)。
  3. 管理员通过 `Performance Board` 查看团队效率、任务完成率和逾期率。
- **通知**: 集成 WebSocket 和邮件通知，支持“一键催报”。

### 3.5 审计系统 (Audit)
- **职责**: 记录系统内关键操作，用于合规与回溯。
- **实现**: 
  - `AuditLog` 模型存储操作人、动作、目标对象及 JSON 格式的变更详情 (`diff`)。
  - 通过 Django Signals (`post_save`, `m2m_changed`) 自动捕获数据变更。

## 4. 业务流程示例

### 4.1 任务创建与分配
1. 用户进入“创建任务”页面。
2. 系统根据用户权限过滤可选项目（仅显示有权限的项目）。
3. 用户填写标题、描述、指派给成员。
4. 提交后，触发 `post_save` 信号：
   - 记录 `AuditLog` (Create)。
   - 触发 `NotificationService` 向被指派人发送站内信/邮件。

### 4.2 日报提交
1. 用户访问工作台，系统检查今日是否已提交。
2. 用户填写本日工作内容、工时。
3. 保存后，系统更新用户的“连签”统计。
4. 每日定时任务（或管理员手动）扫描未提交人员，发送提醒。

## 5. 安全与权限

### 5.1 认证与授权
- 基于 Django Auth 系统。
- 装饰器: `@login_required` 强制登录。
- 函数级权限: `can_manage_project(user, project)`。
- 对象级权限: 在 Views 中通过 `filter(project__in=get_accessible_projects(user))` 隔离数据。

### 5.2 数据安全
- **CSRF**: 全站启用 CSRF 保护。
- **XSS**: 模板自动转义，Markdown 渲染使用白名单标签过滤。
- **文件安全**: 严格限制上传文件后缀（禁止 `.exe`, `.svg`, `.html` 等）。

## 6. 部署与环境
- **配置**: `settings.py` 读取 `.env` 环境变量。
- **静态文件**: `WhiteNoise` (建议) 或 Nginx 托管。
- **数据库**: 默认 SQLite，生产环境建议切换至 MySQL/PostgreSQL。
