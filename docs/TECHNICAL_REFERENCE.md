# 技术参考文档 / Technical Reference

## 1. 系统概览 (System Overview)
本项目是一个基于 Django 的企业级日报与任务管理系统，采用模块化架构设计。核心功能包括项目管理、任务追踪、日报汇报、RBAC 权限控制及实时通知。

## 2. 模块详解 (Module Details)

### 2.1 核心模块 (Core)
- **职责**: 负责用户认证、权限管理 (RBAC)、用户配置及通知系统。
- **关键模型**:
    - `Profile`: 扩展用户属性（职位、部门）。
    - `Role`: 定义角色（如 Developer, Manager）。
    - `Permission`: 定义原子权限（如 `project.view`）。
    - `Notification`: 存储站内通知。
- **关键服务**:
    - `RBACService`: 处理角色与权限的解析、继承与校验。
    - `NotificationService`: 处理通知的创建、WebSocket 推送及邮件发送。

### 2.2 项目模块 (Projects)
- **职责**: 管理项目生命周期、成员分配、附件及阶段流转。
- **关键模型**:
    - `Project`: 项目主体，包含 Key、Owner、Status。
    - `ProjectPhaseConfig`: 自定义项目阶段配置。
    - `ProjectAttachment`: 项目文件管理。
- **关键服务**:
    - `ProjectService`: 处理项目创建、归档及成员变动逻辑。

### 2.3 任务模块 (Tasks)
- **职责**: 任务的全生命周期管理、SLA 追踪、工时记录及评论协作。
- **关键模型**:
    - `Task`: 任务主体，关联 Project 和 User。
    - `TaskComment`: 任务评论（支持 Markdown）。
    - `TaskSlaTimer`: SLA 计时器，追踪响应与解决时间。
- **关键服务**:
    - `TaskStateService`: 管理任务状态机（Open -> In Progress -> Done）。
    - `SLAService`: 计算任务 SLA 指标与逾期状态。

### 2.4 审计模块 (Audit)
- **职责**: 集中记录系统内的关键操作日志，支持回溯与合规检查。
- **关键模型**:
    - `AuditLog`: 通用日志表，记录 Target、Action、User 及 JSON 格式的变更详情。
- **关键服务**:
    - `AuditLogService`: 提供统一的日志写入接口 (`log_change`) 和历史记录查询 (`get_history`)。

### 2.5 报表模块 (Reports)
- **职责**: 提供数据统计、图表分析及日报管理功能。
- **关键模型**:
    - `DailyReport`: 员工每日工作汇报。
    - `ReportJob`: 异步报表任务（用于生成耗时图表）。
- **关键服务**:
    - `StatsService`: 计算燃尽图、累积流图及工时统计数据。

## 3. 技术栈 (Tech Stack)
- **Backend**: Django 5.x, Django Channels (WebSocket)
- **Frontend**: Django Templates, Vue.js 3 (Partial), Chart.js
- **Database**: PostgreSQL / SQLite (Dev)
- **Cache**: Redis / LocMemCache
- **Async**: Python Threading (Simple Jobs), Django Channels
