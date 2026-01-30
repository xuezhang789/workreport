# 任务导出功能文档 / Task Export Documentation

本文档详细说明了任务导出功能的数据结构、接口定义及使用方式。

## 1. 导出字段定义 / Export Fields

任务导出包含以下标准字段：

| 字段名 (中文) | Field Name (English) | 说明 / Description |
| :--- | :--- | :--- |
| ID | ID | 任务唯一标识符 |
| 标题 | Title | 任务标题 |
| 项目 | Project | 所属项目名称 |
| 分类 | Category | 任务类型 (任务/Task, 缺陷/Bug) |
| 状态 | Status | 当前状态 (待处理, 进行中, 已完成等) |
| 优先级 | Priority | 优先级 (高, 中, 低) |
| 负责人 | Assignee | 任务主负责人 |
| 协作人 | Collaborators | 所有协作成员列表 |
| 截止时间 | Due Date | 预计截止时间 (YYYY-MM-DD HH:MM:SS) |
| 完成时间 | Completed At | 实际完成时间 (YYYY-MM-DD HH:MM:SS) |
| 创建时间 | Created At | 任务创建时间 (YYYY-MM-DD HH:MM:SS) |
| SLA 状态 | SLA Status | 基于截止时间的健康度 (normal, tight, overdue) |
| SLA 剩余(h) | SLA Remaining(h) | 距离截止的剩余工时 (考虑暂停时间) |
| URL | URL | 关联链接 |
| 内容 | Content | 任务详情文本 |

## 2. 导出接口 / Export APIs

### 2.1 管理员导出 / Admin Export
- **URL**: `/tasks/admin/export/`
- **Method**: `GET`
- **权限**: 超级管理员或项目管理员
- **参数**:
  - `project`: 项目ID筛选
  - `user`: 用户ID筛选
  - `status`: 状态筛选
  - `priority`: 优先级筛选
  - `q`: 关键词搜索
  - `queue`: `1` (可选) - 强制使用异步队列导出 (推荐大数据量使用)

### 2.2 个人任务导出 / My Tasks Export
- **URL**: `/tasks/export/`
- **Method**: `GET`
- **权限**: 登录用户
- **参数**: 同上
- **行为**:
  - 默认情况下，如果记录数 < 5000，直接返回 CSV 文件流。
  - 如果记录数 > 5000，且未指定 `queue=1`，返回 400 错误提示。
  - 指定 `queue=1` 时，返回 JSON `{"queued": true, "job_id": 123}`，需轮询任务状态。

### 2.3 选中导出 / Selected Export
- **URL**: `/tasks/export/selected/`
- **Method**: `POST`
- **参数**:
  - `task_ids`: 任务ID列表
- **说明**: 导出用户在界面上选中的特定任务。

## 3. 异步导出流程 / Async Export Process

对于大数据量导出，系统采用异步处理机制：
1. 用户请求带 `queue=1` 的导出接口。
2. 服务器创建 `ExportJob` 并返回 `job_id`。
3. 前端轮询 `/reports/export/jobs/<job_id>/status/`。
4. 状态变为 `done` 后，通过 `/reports/export/jobs/<job_id>/download/` 下载文件。
