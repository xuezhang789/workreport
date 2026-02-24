# Projects 模块技术文档

## 1. 模块概述
**模块名称**: Projects (项目管理)
**功能描述**: 核心业务模块，管理项目的全生命周期（创建、进行、结项）、成员权限、阶段流转及项目资产。

## 2. 核心类与方法

### Models (模型)
*   **Project**: 项目主体，包含名称、描述、状态、起止时间。
*   **ProjectMember**: 成员关联表，存储角色（经理/成员/访客）。
*   **ProjectPhaseConfig**: 项目阶段定义（如：需求、开发、测试、部署）。
*   **ProjectAttachment**: 项目文件资料。

### Views (视图)
*   **Project Views (`projects/views.py`)**:
    *   `project_list`: 项目列表（支持卡片/列表视图）。
    *   `project_detail`: 项目详情概览（包含任务统计、动态）。
    *   `project_create` / `project_edit`: 项目维护。
*   **API Views (`projects/views_api.py`)**:
    *   `project_members_api`: 成员管理接口。
    *   `project_search_api`: 高性能搜索接口。

### Forms (表单)
*   **ProjectForm**: 包含性能优化的表单，避免加载全量用户。

## 3. 依赖关系
*   **被依赖**: `tasks` (任务归属), `reports` (日报归属), `work_logs`.
*   **依赖**:
    *   `core`: 权限校验 (`get_accessible_projects`)。
    *   `audit`: 记录项目变更日志。

## 4. 输入输出说明
*   **项目详情页 (`/projects/<id>/`)**:
    *   输入: Project ID.
    *   输出: HTML 页面，包含项目基础信息、成员列表、任务统计图表。
*   **成员添加 API**:
    *   输入: `project_id`, `user_id`, `role`.
    *   输出: JSON `{"status": "ok"}`.
