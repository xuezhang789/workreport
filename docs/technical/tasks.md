# Tasks 模块技术文档

## 1. 模块概述
`Tasks` 模块是协作系统的核心，处理任务的创建、分配、状态流转、SLA 监控、评论互动及附件管理。支持普通任务 (TASK) 和缺陷 (BUG) 两种类型，具有不同的状态机。

## 2. 核心逻辑

### 2.1 状态机 (`tasks.services.state.TaskStateService`)
*   **TASK 流程**: 自由流转，无严格限制。
*   **BUG 流程**: 严格流转 (`New` -> `Confirmed` -> `Fixing` -> `Verifying` -> `Closed`)。
*   **验证**: `validate_transition(category, old_status, new_status)` 确保状态变更合法。

### 2.2 SLA 服务 (`tasks.services.sla`)
*   **计算逻辑**:
    *   基于 `SystemSetting` 中的 `sla_hours` (默认 24h) 计算截止时间。
    *   支持暂停计时 (如状态为 `Blocked`)，通过 `SLATimer` 模型记录暂停时长。
    *   状态判断: `Normal` (正常), `Tight` (紧张, <4h), `Overdue` (逾期)。
*   **性能注意**: 目前部分 SLA 状态计算在 Python 层进行，大数据量下存在优化空间。

### 2.3 任务模型 (`tasks.models.Task`)
*   **字段**: `title`, `content`, `status`, `priority`, `category` (TASK/BUG).
*   **关联**: `project` (FK), `user` (Assignee), `collaborators` (M2M).
*   **附件**: `TaskAttachment`，关联到具体任务和上传者。

## 3. 视图与接口
*   **`admin_task_list`**: 统一任务管理台。
    *   *特性*: 支持多维度筛选、SLA 预警排序、批量操作。
*   **`task_detail`**: 任务详情页。
    *   *功能*: 状态变更、评论 (支持 `@mention`)、文件拖拽上传、历史记录查看。
*   **`admin_task_stats`**: 任务统计看板。
    *   *指标*: 完成率、逾期率、平均处理时长、新增/完成趋势图。

## 4. 安全与权限
*   **创建权限**: 目前仅限 **管理员** 和 **项目经理** 创建任务（严格模式）。普通成员不可创建。
*   **上传权限**: 仅任务负责人、协作者或项目管理者可上传附件。
*   **XSS 防护**: 详情页使用 `safe_md` 过滤器渲染 Markdown，确保 HTML 安全。

## 5. 已知问题与优化点
*   **模板渲染**: `task_detail.html` 中存在 `|escape|safe_md` 双重转义问题，需修复。
*   **SLA 查询**: 热门/紧急任务筛选依赖内存计算，建议持久化 `sla_deadline` 字段。
