# 技术文档 (Technical Documentation)

## 1. 项目管理模块 (Projects Module)

### 1.1 模块概述 (Overview)
项目管理模块是系统的核心业务单元，负责项目的全生命周期管理，包括创建、编辑、阶段流转、成员管理、附件管理及历史审计。

**主要文件**:
- 模型: `projects/models.py`
- 视图: `projects/views.py`
- 接口: `projects/views_api.py`

### 1.2 核心模型 (Core Models)

#### 1.2.1 Project (项目)
核心实体，代表一个具体的工程或任务集合。

| 字段名 | 类型 | 描述 | 约束 |
| :--- | :--- | :--- | :--- |
| name | CharField | 项目名称 | max_length=200 |
| code | CharField | 项目代号 | Unique, max_length=50 |
| owner | ForeignKey | 项目负责人 | User, related_name='owned_projects' |
| members | ManyToMany | 项目成员 | User, related_name='project_memberships' |
| managers | ManyToMany | 项目经理 | User, related_name='managed_projects' |
| current_phase | ForeignKey | 当前阶段 | ProjectPhaseConfig |
| overall_progress | DecimalField | 总体进度 | 0-100% |
| is_active | BooleanField | 是否激活 | Default=True, Indexed |

**核心方法**:
- 无复杂业务方法，逻辑主要在 Service 层或 View 层处理。

#### 1.2.2 ProjectPhaseConfig (项目阶段配置)
定义项目的生命周期阶段（如：启动、开发、测试、验收）。

| 字段名 | 类型 | 描述 |
| :--- | :--- | :--- |
| phase_name | CharField | 阶段名称 |
| progress_percentage | Integer | 关联进度百分比 (0-100) |
| order_index | Integer | 排序索引 |

### 1.3 核心业务流程 (Core Business Flows)

#### 1.3.1 项目列表与筛选 (Project List & Filtering)
- **入口**: `projects.views.project_list`
- **逻辑**:
    1.  **基础过滤**: `_filtered_projects` 函数处理搜索 (`q`)、日期范围、负责人筛选。
    2.  **权限控制**: `get_accessible_projects(user)` 确保用户只能看到有权限的项目（RBAC + 成员关系）。
    3.  **性能优化**: 使用 `select_related('owner', 'current_phase')` 减少数据库查询。
    4.  **聚合计算**: 使用 `annotate(member_count=Count('members'))` 避免 N+1 查询。
- **输入**: `request.GET` (q, phase, owner, sort, page)
- **输出**: `page_obj` (Project QuerySet)

#### 1.3.2 项目详情 (Project Detail)
- **入口**: `projects.views.project_detail`
- **逻辑**:
    1.  **权限检查**: 必须是 Superuser 或 Accessible Projects 之一。
    2.  **数据获取**: 获取项目详情，并预取 `members`, `managers`。
    3.  **统计计算**: 计算任务统计 (Total, Completed, Overdue, SLA)。
        - **优化**: 使用 `cache.get/set` 缓存统计结果 5 分钟 (`project_stats_{id}_{count}`)。
    4.  **SLA 计算**: 实时计算当前页任务的 SLA 状态。

#### 1.3.3 项目阶段流转 (Phase Transition)
- **入口**: `projects.views.project_update_phase` (AJAX)
- **逻辑**:
    1.  验证用户是否有管理权限 (`can_manage_project`)。
    2.  更新 `current_phase` 和 `overall_progress`。
    3.  记录变更日志 `ProjectPhaseChangeLog`。
    4.  **异步通知**: 发送邮件给负责人/管理员，发送站内信给所有成员。

### 1.4 依赖关系 (Dependencies)
- **Core Module**: 依赖 `core.permissions` (RBAC), `core.utils` (Validation)。
- **Tasks Module**: 依赖 `tasks.models.Task` 进行进度统计。
- **Audit Module**: 依赖 `audit.services.AuditLogService` 记录操作历史。
- **Reports Module**: 依赖 `reports.utils.get_accessible_projects` 进行权限过滤。

### 1.5 异常处理 (Error Handling)
- **403 Forbidden**: 权限不足时返回 `_admin_forbidden` 或 `JsonResponse({'error': 'Permission denied'})`。
- **404 Not Found**: ID 不存在时抛出 `Http404`。
- **Form Validation**: 创建/编辑时自动校验表单，失败则重新渲染页面并显示错误。

---

## 2. 团队管理模块 (Team Management Module)

### 2.1 模块概述
负责管理项目成员的分配、角色变更及跨项目的人员调度。

### 2.2 核心视图 (Core Views)

#### 2.2.1 成员添加 (Add Member to Project)
- **入口**: `reports.views_teams.team_member_add_project`
- **逻辑**:
    1.  检查权限 (当前存在缺陷：仅检查全局权限，未检查特定项目权限)。
    2.  调用 `team_service.add_member_to_project` 执行添加。
    3.  **WebSocket 广播**: 通过 `team_updates_global` 频道通知前端实时更新。
- **输入**: `user_id`, `project_id`
- **输出**: JSON (Status, Updated Project List)

---
