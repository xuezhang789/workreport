# Audit 模块技术文档

## 1. 模块概述
**模块名称**: Audit (审计与日志)
**功能描述**: 系统的“黑匣子”，负责全链路记录用户操作痕迹、数据变更历史（Diff）及安全审计。

## 2. 核心类与方法

### Models (模型)
*   **AuditLog**:
    *   `actor`: 操作人。
    *   `action`: 动作 (CREATE, UPDATE, DELETE, LOGIN, DOWNLOAD)。
    *   `target_content_type` / `target_object_id`: 关联目标对象。
    *   `changes`: JSON 格式存储的变更前后差异 (Diff)。
    *   `ip_address`: 操作来源 IP。
*   **TaskHistory**: 专门用于任务字段变更的高频历史记录表。

### Services (服务)
*   **AuditLogService (`audit/services.py`)**:
    *   `log_action(user, obj, action, changes)`: 记录审计日志。
    *   `get_logs_for_object(obj)`: 获取特定对象的审计历史。
    *   `format_changes(changes)`: 将 JSON Diff 格式化为人类可读文本。

### Middleware (中间件)
*   **AuditMiddleware (`audit/middleware.py`)**:
    *   拦截每个请求，捕获当前用户和 IP，供 Model Signal 或 Service 使用。

## 3. 依赖关系
*   **被依赖**: `core`, `projects`, `tasks`, `reports` (业务模块在增删改时调用 Audit)。
*   **依赖**:
    *   `core.User`: 记录操作人。
    *   `django.contrib.contenttypes`: 实现通用关联。

## 4. 输入输出说明
*   **日志记录 (Internal Call)**:
    *   输入: `user`, `project_instance`, `action="UPDATE"`, `changes={"status": ["old", "new"]}`.
    *   输出: 创建一条 `AuditLog` 记录。
*   **审计查询 API**:
    *   输入: `target_id`, `target_type`.
    *   输出: JSON 列表，包含操作时间、操作人、变更详情。
