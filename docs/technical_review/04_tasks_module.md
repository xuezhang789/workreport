# Tasks 模块技术文档

## 1. 模块概述
**模块名称**: Tasks (任务管理)
**功能描述**: 提供任务的创建、分配、状态流转、SLA 监控及协作功能。支持普通任务和缺陷 (Bug) 两种模式。

## 2. 核心类与方法

### Models (模型)
*   **Task**: 任务主体，包含标题、描述、优先级、状态、截止时间、SLA 倒计时。
*   **TaskComment**: 任务评论。
*   **TaskAttachment**: 任务附件。
*   **TaskSlaTimer**: 记录 SLA 暂停/恢复的时间片段。

### Services (服务)
*   **StateService (`tasks/services/state.py`)**:
    *   `transit_status(task, new_status)`: 执行状态流转，处理副作用（如 Bug 流程强制校验）。
*   **SlaService (`tasks/services/sla.py`)**:
    *   `calculate_remaining_time(task)`: 计算 SLA 剩余时间。
    *   `toggle_pause(task)`: 暂停/恢复 SLA 计时。
*   **ExportService (`tasks/services/export.py`)**:
    *   `get_export_rows(queryset)`: 生成任务导出数据（存在 N+1 优化空间）。

### Views (视图)
*   `task_kanban`: 看板视图。
*   `task_detail`: 任务详情及操作入口。
*   `my_tasks`: “我的任务”聚合页。

## 3. 依赖关系
*   **依赖**:
    *   `projects`: 任务必须归属于项目。
    *   `core`: 指派给用户。
    *   `audit`: 记录状态变更和评论。

## 4. 输入输出说明
*   **任务创建**:
    *   输入: 标题、描述、负责人、优先级、类型、截止时间。
    *   输出: 新任务对象，自动计算初始 SLA。
*   **状态流转 API**:
    *   输入: `task_id`, `new_status`.
    *   输出: 更新任务状态，记录审计日志，触发通知。
