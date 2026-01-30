# WorkReport 项目技术文档

## 1. 项目概览

WorkReport 是一个基于 Django 框架开发的企业级项目管理与工作汇报系统。旨在提供高效的任务追踪、项目进度管理以及团队工作日志汇报功能。系统采用模块化设计，支持精细化的权限控制和灵活的流程配置。

### 技术栈
- **后端框架**: Django (Python 3.13)
- **数据库**: SQLite (开发环境) / 可配置 PostgreSQL (生产环境)
- **前端技术**: Django Templates, 原生 JavaScript, CSS (自定义设计系统)
- **异步任务**: Celery (可选，用于导出等耗时任务)
- **其他依赖**: Channels (WebSocket), Whitenoise (静态文件)

## 2. 系统架构与模块划分

系统主要由以下核心应用（Apps）组成：

### 2.1 Core (核心基础)
- **职责**: 提供全系统的基础服务，包括用户扩展模型、全局权限矩阵、通知系统和异步导出任务管理。
- **关键模型**:
    - `Profile`: 扩展用户属性，定义职位角色（Position）。
    - `PermissionMatrix`: 定义全局角色的基础权限（目前主要作为参考模型，实际逻辑在 utils 中）。
    - `Notification`: 站内消息通知。
    - `ExportJob`: 异步文件导出任务记录。

### 2.2 Projects (项目管理)
- **职责**: 管理项目的全生命周期，包括创建、阶段流转、成员分配和进度追踪。
- **关键模型**:
    - `Project`: 项目主体。
    - `ProjectPhaseConfig`: 自定义项目阶段配置。
    - `ProjectMemberPermission`: 项目成员的细粒度权限。

### 2.3 Tasks (任务管理)
- **职责**: 处理具体的执行任务，支持状态流转、优先级管理、SLA 计时和协作。
- **关键模型**:
    - `Task`: 任务实体。
    - `TaskSlaTimer`: SLA 计时器，支持暂停/恢复。
    - `TaskTemplateVersion`: 任务模板。

### 2.4 Work Logs (工作日志与报表)
- **职责**: 负责日报/周报的填报、统计和催报。
- **关键模型**:
    - `DailyReport`: 日报记录。
    - `ReminderRule`: 提醒规则配置。
    - `ReportMiss`: 缺报记录。

### 2.5 Audit (审计系统)
- **职责**: 记录系统内的关键操作日志，用于安全审计和历史回溯。
- **关键模型**: `AuditLog`, `TaskHistory`.

## 3. 核心业务流程与实现

### 3.1 权限控制体系
系统采用**混合权限控制机制**：
1.  **全局角色权限**: 基于 `Profile.position`，决定用户在系统层面的基础能力。
    *   `core.permissions.has_manage_permission`: 检查用户是否为管理员角色 (mgr, pm)。
2.  **项目级权限**: 
    *   基于 `Project` 的成员列表 (`owner`, `managers`, `members`)。
    *   `reports.utils.can_manage_project`: 核心鉴权函数，判断用户是否对特定项目拥有管理权。
    *   `get_accessible_projects`: 获取用户有权访问的所有项目列表，用于过滤 QuerySet。

### 3.2 任务 SLA 管理 (Service Level Agreement)
SLA 是任务管理的核心特性：
- **计时机制**: 通过 `TaskSlaTimer` 记录任务的 `total_paused_seconds`。
- **状态计算**: 结合 `due_at` (截止时间) 和当前时间，计算剩余时间。
- **暂停逻辑**: 当任务状态变为 `BLOCKED` 或手动暂停时，计时器停止，暂停期间不计入消耗时间。
- **阈值提醒**: 系统设置 (`SystemSetting`) 定义了 `amber` (警告) 和 `red` (紧急) 阈值，用于 UI 高亮和通知。

### 3.3 报表自动化
- **填报**: 用户根据角色模板填写日报。
- **防重**: 同一用户在同一日期同一角色下只能有一份日报。
- **批量创建**: 提供 API 支持批量导入日报，已优化 N+1 查询问题。

### 3.4 审计日志
- **全量记录**: 关键操作（增删改）通过 `AuditLogService` 写入 `AuditLog`。
- **历史回溯**: 项目和任务详情页提供完整的历史变更记录 (`TaskHistory`, `ProjectHistory`)。

## 4. 安全与配置
- **环境隔离**: 敏感配置 (`SECRET_KEY`, `DEBUG`, `DB`) 均通过环境变量加载。
- **API 安全**: 
    - 关键 API 均有 `@login_required` 保护。
    - 敏感操作（如搜索）增加了简单的节流 (`_throttle`)。
- **输入验证**: 文件上传经过 `_validate_file` 检查，防止恶意文件上传。

## 5. 待完善/待审查点
- **PermissionMatrix**: 模型存在但未被深度集成，目前权限逻辑较为硬编码。
- **邮件发送**: 目前部分邮件发送为同步操作，建议全面异步化。
