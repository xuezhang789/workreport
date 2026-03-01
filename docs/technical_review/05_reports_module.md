# Reports & WorkLogs 模块技术文档

## 1. 模块概述
**模块名称**: Reports (效能分析) & WorkLogs (日报管理)
**功能描述**: 
*   **WorkLogs**: 负责日报的数据存储、模板定义和缺报检查。
*   **Reports**: 负责日报的业务处理、统计分析、效能看板展示及报表导出。

## 2. 核心类与方法

### Models (`work_logs`)
*   **DailyReport**: 日报宽表，包含 `summary`, `plan`, `problems` 及各角色特定字段。
*   **ReportMiss**: 缺报记录表。
*   **ReminderRule**: 自动催报规则配置。
*   **RoleTemplate**: 基于角色的日报模板配置。

### Services (`reports/services`)
*   **StatsService (`stats.py`)**:
    *   `get_performance_stats`: 计算交付周期 (Lead Time)、缺陷率、SLA 达成率。
    *   `get_member_velocity`: 计算成员速率。
*   **NotificationService**: 处理邮件和 WebSocket 消息推送。
*   **AuditService**: 审计日志封装。

### Views (`reports`)
*   `daily_report_create`: 日报填写页面，动态加载角色模板。
*   `performance_board`: 效能仪表盘。
*   `export_reports`: 日报数据导出。

## 3. 依赖关系
*   **依赖**:
    *   `core`: 用户与权限。
    *   `projects`: 日报关联项目。
    *   `tasks`: 统计服务依赖任务数据计算效能指标。
    *   `celery`: 异步发送提醒和处理大数据导出。

## 4. 输入输出说明
*   **效能看板 API**:
    *   输入: 时间范围 (start_date, end_date), 项目 ID.
    *   输出: JSON 数据，包含 `lead_time_avg`, `bug_rate`, `completion_rate`.
*   **日报提交**:
    *   输入: 表单数据（包含公共字段及角色特定字段）。
    *   输出: 保存 `DailyReport`，更新“连签”状态，触发通知。
