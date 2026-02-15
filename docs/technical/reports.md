# Reports & Audit 模块技术文档

## 1. Reports 模块
`Reports` 模块负责数据聚合、报表生成和系统通知。

### 1.1 核心组件
*   **DailyReport (`reports.models.DailyReport`)**: 
    *   用户每日工作填报，关联多个项目。
    *   支持 markdown 内容。
*   **Statistics (`reports.services.stats`)**:
    *   提供项目级、用户级、团队级的 KPI 计算。
    *   使用 Django Aggregation 优化查询性能。
*   **Notifications (`reports.services.notification_service`)**:
    *   多渠道通知：站内信 (Database) + 实时推送 (WebSocket/Channels)。
    *   触发场景：任务分配、状态变更、评论提及、SLA 预警。

### 1.2 模板标签
*   **`safe_md`**: 安全的 Markdown 渲染器，白名单机制过滤 HTML 标签。

---

## 2. Audit 模块
`Audit` 模块提供全系统的操作审计日志，满足合规性要求。

### 2.1 数据模型
*   **AuditLog (`audit.models.AuditLog`)**:
    *   `action`: create, update, delete, login, export.
    *   `target`: 记录操作对象的类型和 ID。
    *   `details`: JSONField，记录字段变更前后的值 (`diff`)。
    *   `ip`: 操作者 IP 地址。

### 2.2 自动审计
*   **Middleware (`audit.middleware.AuditMiddleware`)**: 
    *   (可选) 自动捕获特定 HTTP 方法的请求并记录日志。
*   **Services (`audit.utils.log_action`)**:
    *   在业务逻辑中显式调用，记录高语义的操作日志（如“批量完成任务”）。

### 2.3 历史回溯
*   **TaskHistory**: 
    *   专门用于展示任务的时间轴视图。
    *   支持按字段（状态、经办人、截止时间）筛选历史变更。
