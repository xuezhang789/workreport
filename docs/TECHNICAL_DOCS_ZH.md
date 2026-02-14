# WorkReport 项目技术文档

## 1. 项目概述
WorkReport 是一个基于 Django 的企业级项目协作与日报管理系统。它集成了项目管理、任务追踪、SLA 监控、RBAC 权限控制及多维绩效报表等功能，旨在提升团队协作效率与透明度。

## 2. 系统架构

### 2.1 技术栈
- **后端**: Python 3.12+, Django 5.x
- **数据库**: SQLite (开发环境) / PostgreSQL, MySQL (生产环境支持)
- **前端**: Django Templates, HTMX (局部刷新), Bootstrap 5 (UI框架), Chart.js/ApexCharts (图表)
- **异步任务**: Celery + Redis (邮件发送、报表导出)
- **服务器**: Daphne (ASGI) / Gunicorn (WSGI)

### 2.2 模块划分
系统采用模块化设计，核心应用如下：

| 应用名称 | 职责描述 | 关键模型 |
| :--- | :--- | :--- |
| **core** | 基础设施 | `Profile`, `SystemSetting`, `Notification`, `ExportJob` (及 RBAC 核心模型) |
| **projects** | 项目管理 | `Project`, `ProjectPhaseConfig`, `ProjectMemberPermission` |
| **tasks** | 任务协作 | `Task`, `TaskComment`, `TaskSlaTimer`, `TaskAttachment` |
| **work_logs** | 日报数据 | `DailyReport`, `ReportMiss`, `ReminderRule`, `RoleTemplate` |
| **reports** | 统计与视图 | (主要包含 View 逻辑，数据模型复用 `work_logs`) |
| **audit** | 审计日志 | `AuditLog`, `TaskHistory` |

## 3. 核心功能与业务流程

### 3.1 权限控制 (RBAC)
系统实现了基于资源的访问控制 (RBAC)，支持全局角色与项目级角色。
- **模型设计**: 通过 `UserRole` 关联 `User` 与 `Role`，并可指定 `scope`（如特定项目 ID）。
- **权限校验**: `core.services.rbac` 提供 `has_permission(user, action, resource)` 接口，支持层级权限判断。

### 3.2 项目全生命周期
1. **立项**: 管理员创建项目，配置 `ProjectPhaseConfig`（定义项目阶段流转）。
2. **执行**: 项目经理分配成员，更新 `overall_progress` 和 `current_phase`。
3. **监控**: 自动记录 `ProjectPhaseChangeLog`，通过甘特图与燃尽图可视化进度。

### 3.3 任务与 SLA 监控
- **SLA 引擎**: 任务创建时启动计时器 (`TaskSlaTimer`)。
  - 支持 **暂停** (On Hold) 与 **恢复**，系统自动扣除暂停时长计算实际耗时。
  - 根据剩余时间自动标记状态：正常 (Green)、预警 (Amber)、逾期 (Red)。
- **协作**: 支持富文本评论、@提及通知及文件附件。

### 3.4 日报与绩效体系
- **智能填报**: 用户创建日报时，系统自动聚合其当日 `Done` 状态的任务作为“今日产出”。
- **缺报管理**: 定时任务检测未提交人员，生成 `ReportMiss` 记录并触发提醒。
- **绩效看板**:
  - **个人维度**: 任务完成率、平均响应时间、代码/文档产出量。
  - **团队维度**: 部门人效对比、SLA 达标率趋势。

### 3.5 审计与合规
- **全链路追踪**: 关键模型的 `save` 和 `delete` 信号触发 `AuditLog` 记录。
- **Diff 记录**: 审计日志详细存储字段变更前后的值 (Old Value vs New Value)。

## 4. 关键实现细节

### 4.1 异步导出机制
为避免大文件导出阻塞主线程，采用 `ExportJob` + Celery 模式：
1. 用户发起导出请求，系统创建 `ExportJob` (状态: Pending)。
2. Celery Worker 后台生成 Excel/CSV，上传至存储。
3. 任务完成后更新 Job 状态，并通过 WebSocket/邮件通知用户下载。

### 4.2 性能优化策略
- **N+1 查询优化**: 在 `ListView` 中广泛使用 `select_related` (外键) 和 `prefetch_related` (M2M)。
- **缓存策略**: 用户的权限列表 (`user_permissions`) 在 Session 或 Redis 中缓存，减少 DB 命中。
- **HTMX**: 在任务看板拖拽、评论加载等高频交互场景使用 HTMX 实现局部刷新，减少全页重载。

## 5. 部署与运维
- **配置管理**: 使用 `python-dotenv` 加载环境变量 (.env)。
- **静态文件**: 生产环境建议使用 Whitenoise 或 Nginx 托管 `STATIC_ROOT`。
- **定时任务**: 使用 Celery Beat 调度日报提醒与缺报检查。
