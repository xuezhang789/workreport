# Projects 模块技术文档

## 1. 模块概述
`Projects` 模块负责管理项目的全生命周期，包括项目的创建、阶段配置、成员管理以及项目级附件。它是任务和报表的聚合根。

## 2. 数据模型

### 2.1 Project (`projects.models.Project`)
*   **核心字段**:
    *   `name`, `code`: 项目标识。
    *   `owner`: 项目拥有者 (FK to User)。
    *   `managers`: 项目经理列表 (M2M to User)。
    *   `members`: 项目成员列表 (M2M to User)。
    *   `status`: 项目状态 (Active, Archived, etc.)。
*   **关键逻辑**:
    *   通过 M2M 字段定义了三级权限体系 (Owner > Managers > Members)。

### 2.2 ProjectPhase (`projects.models.ProjectPhase`)
*   **用途**: 定义项目开发的各个阶段（如：需求、设计、开发、测试）。
*   **关联**: 属于 `Project`，可排序。

## 3. 核心视图 (`projects.views`)
*   **`project_list`**: 展示用户可访问的项目列表。
    *   *逻辑*: 使用 `get_accessible_projects` 过滤。
*   **`project_detail`**: 项目概览页，聚合显示项目进度、近期任务、成员列表。
*   **`project_create/edit`**: 项目元数据管理。
    *   *权限*: 仅超级用户或（编辑时）项目拥有者/经理可操作。

## 4. 权限与可见性
*   **严格隔离**: 普通用户只能看到自己参与 (`members`) 或管理 (`managers/owner`) 的项目。
*   **操作权限**:
    *   **查看**: Members + Managers + Owner + Superuser.
    *   **编辑**: Managers + Owner + Superuser.
    *   **删除**: Owner + Superuser.

## 5. 交互设计
*   **前端组件**: 使用 `VirtualProjectSelect` (虚拟滚动下拉框) 处理大量项目数据的选择性能问题。
