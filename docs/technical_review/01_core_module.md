# Core 模块技术文档

## 1. 模块概述
**模块名称**: Core (核心基础服务)
**功能描述**: 负责系统的基础设施，包括用户管理、权限控制 (RBAC)、文件上传、系统配置和通用工具。它是所有业务模块的基础依赖。

## 2. 核心类与方法

### Models (模型)
*   **Profile**: 扩展 Django User 模型，存储职位、部门、头像等信息。
*   **Permission / Role / UserRole**: RBAC 权限系统的核心，支持基于角色的权限控制。
*   **SystemSetting**: 键值对形式的系统全局配置。
*   **ChunkedUpload**: 支持大文件分片上传及断点续传。
*   **Notification**: 系统通知存储。

### Services (服务)
*   **RBACService (`core/services/rbac.py`)**:
    *   `check_permission(user, permission_code)`: 检查用户是否拥有特定权限。
    *   `get_user_roles(user)`: 获取用户所有角色。
    *   `assign_role(user, role)`: 为用户分配角色。
*   **UploadService (`core/services/upload_service.py`)**:
    *   `handle_chunk(file, chunk_index)`: 处理文件分片上传。
    *   `merge_chunks(upload_id)`: 合并分片并保存为最终文件。
*   **NotificationTemplateService**: 渲染通知模板。

### Views (视图)
*   **Authentication**: `register`, `login_view`, `logout_view`.
*   **Profile**: `account_settings` (个人中心).
*   **Search**: `global_search` (全局搜索聚合).
*   **Upload**: `upload_init`, `upload_chunk`, `upload_complete`.

## 3. 依赖关系
*   **被依赖**: `projects`, `tasks`, `reports`, `audit`, `work_logs` (所有业务模块均依赖 Core)。
*   **依赖**:
    *   `django.contrib.auth`: 用户认证。
    *   `audit`: 记录关键操作日志。
    *   `projects/tasks/reports`: `global_search` 存在反向依赖，用于聚合搜索结果。

## 4. 输入输出说明
*   **全局搜索 (`/search/`)**:
    *   输入: `q` (关键词), `type` (类型过滤).
    *   输出: 包含项目、任务、日报的聚合列表 (HTML/JSON).
*   **文件上传 (`/upload/chunk/`)**:
    *   输入: `file` (分片数据), `upload_id`, `chunk_index`.
    *   输出: `{"status": "success", "next_chunk": 5}`.
