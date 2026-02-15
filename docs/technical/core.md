# Core 模块技术文档

## 1. 模块概述
`Core` 模块是系统的基础设施层，负责提供全局通用的服务、模型和工具函数。它处理用户认证扩展、基于角色的权限控制 (RBAC)、文件上传、系统设置以及基础的工具类。

## 2. 关键组件

### 2.1 文件上传服务 (`core.services.upload_service`)
*   **用途**: 处理大文件分片上传和标准文件上传。
*   **类**: `UploadService`
*   **主要方法**:
    *   `init_chunked_upload`: 初始化分片上传会话，创建临时文件。
    *   `process_chunk`: 写入文件分片（支持断点续传）。
    *   `complete_chunked_upload`: 合并分片，校验大小，返回 Django `ContentFile` 对象。
*   **数据模型**: `ChunkedUpload` (记录上传会话状态)。

### 2.2 权限控制 (`core.services.rbac` & `core.permissions`)
*   **用途**: 提供比 Django 默认 Group 更细粒度的项目级权限控制。
*   **逻辑**:
    *   `can_manage_project(user, project)`: 检查用户是否为超级用户、项目拥有者或经理。
    *   `get_accessible_projects(user)`: 返回用户有权查看的所有项目 QuerySet。
*   **角色定义**:
    *   `Owner`: 项目拥有者（全权）。
    *   `Manager`: 项目经理（管理任务、成员，但不可删除项目）。
    *   `Member`: 普通成员（仅查看、评论、处理分配的任务）。

### 2.3 基础模型 (`core.models`)
*   **Profile**: 用户扩展信息（头像、职位、部门、电话）。
*   **SystemSetting**: 键值对存储的动态系统配置（如 SLA 阈值）。
*   **ExportJob**: 异步导出任务的状态追踪。

## 3. 安全性设计
*   **文件上传**: 
    *   限制文件扩展名 (`UPLOAD_ALLOWED_EXTENSIONS`)。
    *   限制文件大小 (`UPLOAD_MAX_SIZE`)。
    *   *待增强*: 文件内容魔数 (Magic Number) 校验。
*   **CSV 导出**:
    *   `_sanitize_csv_cell`: 防止 CSV 注入攻击 (CSV Injection)，对以 `=, +, -, @` 开头的单元格进行转义。

## 4. 依赖关系
*   **依赖**: `Django`, `channels` (部分工具), `os`, `shutil`.
*   **被依赖**: `projects`, `tasks`, `reports`, `audit` (几乎所有业务模块)。
