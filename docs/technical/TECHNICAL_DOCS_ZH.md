# 技术文档 (Technical Documentation)

本文档详细描述了系统的各个功能模块、核心逻辑、输入输出参数及依赖关系。

## 1. 核心模块 (Core Module)

### 1.1 RBAC 权限控制服务 (`core.services.rbac.RBACService`)
**功能描述**: 
提供基于角色的访问控制（RBAC）核心功能，支持全局角色和基于范围（Scope）的角色（如项目级角色）。实现了权限的查询、验证、缓存管理及角色分配。

**核心模型**:
- `Role`: 角色定义，支持继承 (`parent`)。
- `Permission`: 权限原子定义 (`code`, `group`)。
- `UserRole`: 用户与角色的关联，支持 `scope` (e.g., `project:1`)。
- `RolePermission`: 角色与权限的关联。

**核心方法**:
- `get_user_permissions(user, scope=None)`: 获取用户在指定范围内的所有权限代码集合。支持缓存 (`CACHE_TIMEOUT=3600s`) 和角色继承解析。
- `has_permission(user, permission_code, scope=None)`: 检查用户是否拥有特定权限。
- `assign_role(user, role, scope=None)`: 分配角色并清除缓存。
- `get_scopes_with_permission(user, permission_code)`: 反向查询用户在哪些 Scope 下拥有指定权限。

**依赖关系**:
- Django Cache (Redis/Locmem)
- `django.contrib.auth.models.User`

### 1.2 基础模型 (`core.models`)
**Profile (用户资料)**:
- 扩展 Django User，存储职位 (`position`)、人事信息（入职日期、薪资、中介信息）等。
- 职位选项: `dev`, `qa`, `pm`, `ui`, `ops`, `mgr`。

**SystemSetting (系统设置)**:
- 简单的键值对存储，用于动态配置（如 `sla_hours`）。

**Notification (通知)**:
- 存储站内信，支持优先级、类型 (`task_assigned`, `bug_created` 等) 和 JSON 数据负载。

---

## 2. 项目管理模块 (Projects Module)

### 2.1 项目模型 (`projects.models.Project`)
**功能描述**:
管理项目的生命周期、成员、阶段和进度。

**关键字段**:
- `code`: 项目代号（唯一）。
- `owner`: 项目负责人。
- `members` / `managers`: 成员和管理员的多对多关系。
- `current_phase`: 当前阶段 (`ProjectPhaseConfig`)。
- `overall_progress`: 总体进度百分比。
- `sla_hours`: 项目级 SLA 配置。

**关联模型**:
- `ProjectPhaseConfig`: 定义项目的各个阶段（如“需求分析”、“开发”、“测试”）。
- `ProjectPhaseChangeLog`: 记录阶段变更历史。
- `ProjectAttachment`: 项目附件管理。

### 2.2 项目视图逻辑 (`projects.views`)
- **列表页**: 支持按名称、代号、负责人、日期筛选；支持按阶段过滤；使用 `select_related` 优化查询。
- **详情页**: 展示项目概况、SLA 统计（完成率、逾期数）、任务列表（支持排序和状态过滤）。
- **权限控制**: 结合 `RBACService` 和 `get_accessible_projects` 工具函数，确保用户只能访问授权项目。

---

## 3. 任务管理模块 (Tasks Module)

### 3.1 任务模型 (`tasks.models.Task`)
**功能描述**:
核心业务对象，管理任务的全生命周期。

**关键字段**:
- `category`: 分类 (`task`, `bug`, `requirement`)。
- `status`: 状态流转（不同分类有不同状态集）。
- `priority`: 优先级 (`high`, `medium`, `low`)。
- `due_at` / `completed_at`: SLA 计算基础。
- `collaborators`: 协作人员。

**核心逻辑**:
- **状态流转**: `TaskStateService` (`tasks/services/state.py`) 定义了严格的状态流转规则（特别是 Bug 工作流）。
- **SLA 计时**: `TaskSlaTimer` 记录任务暂停时长，用于计算净耗时。
- **原子性更新**: 状态更新使用 `transaction.atomic` 确保数据一致性。

### 3.2 任务服务
- **TaskStateService**: 验证状态流转合法性，获取特定分类的状态集。
- **SLA Calculation**: `tasks.services.sla` 计算剩余时间、逾期状态，扣除暂停时间。

---

## 4. 报表与通知模块 (Reports & Notifications)

### 4.1 通知服务 (`reports.services.notification_service`)
**功能描述**:
统一的通知发送入口，支持多渠道分发。

**核心流程**:
1. **DB 存储**: 创建 `Notification` 记录。
2. **WebSocket 推送**: 通过 Django Channels 推送实时消息。
3. **邮件发送**: 异步调用 Celery 任务 `send_email_async_task` 发送邮件。

**输入参数**:
- `user`: 接收用户。
- `title`/`message`: 内容。
- `notification_type`: 业务类型。
- `priority`: 优先级。

### 4.2 异步任务 (`reports.tasks`)
- `cleanup_old_logs_task`: 定期清理过期的 `AuditLog` 和 `Notification`（默认 180 天）。
- `send_email_async_task`: 异步发送邮件，避免阻塞主线程。
- `generate_export_file_task`: 处理大数据量导出。

---

## 5. 审计模块 (Audit Module)

### 5.1 审计日志 (`audit.models.AuditLog`)
**功能描述**:
记录系统内的关键操作轨迹。

**关键字段**:
- `action`: 动作类型 (`create`, `update`, `delete`, `access` 等)。
- `target_type` / `target_id`: 操作对象多态引用。
- `details`: JSON 字段，存储变更前后的 Diff 信息。
- `result`: 操作结果 (`success`, `failure`)。

**核心算法**:
- **Diff 计算**: `AuditService._calculate_diff` 比较模型实例的字段差异，对于外键字段比较 ID 而非对象实例。

---

## 6. 异常处理机制

- **全局异常**: Django 中间件捕获未处理异常。
- **视图层**: 使用 `try-except` 块包裹业务逻辑，通过 `messages` 框架向用户反馈错误，或返回标准化的 `JsonResponse` (API)。
- **事务回滚**: 关键写操作（如任务状态更新、项目创建）使用 `transaction.atomic`，发生异常时自动回滚。

## 7. 性能优化策略

- **数据库查询**:
  - 广泛使用 `select_related` (FK) 和 `prefetch_related` (M2M) 解决 N+1 问题。
  - 使用 `annotate` 进行聚合计算（如项目成员数）。
  - 为常用查询字段（状态、创建时间、外键）建立数据库索引。
- **缓存**:
  - RBAC 权限结果缓存 (1小时)。
  - 项目统计信息缓存 (5分钟)。
- **异步处理**:
  - 邮件发送、文件导出、日志清理通过 Celery 异步执行。
