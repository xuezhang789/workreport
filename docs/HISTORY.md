# 项目变更历史 / Project Change History

本文档记录了 WorkReport 项目的演进过程，包括功能更新、架构重构、Bug 修复及数据库变更。
This document records the evolution of the WorkReport project, including feature updates, architectural refactoring, bug fixes, and database changes.

---

## 2026-01-27

### 🔍 审计日志系统重构 / Audit Log System Refactor
- **Commit**: `034d260` (优化日志页面 / Optimize log page)
- **Author**: XueZhang / TraeAI
- **Type**: Refactor & Feature
- **变更详情 / Details**:
  - **Model**: 重构 `AuditLog` 模型，移除非结构化字段 (`changes`, `data`, `entity_type`)，引入结构化字段 (`target_type`, `result`, `details` JSON)。
  - **UI**: 全新设计“审计日志”页面，支持 JSON 详情折叠查看、状态徽章显示及高级筛选（响应式网格布局）。
  - **Logic**: 统一日志记录入口 `AuditService`，自动计算字段差异 (`diff`)。
- **Database**: `0014_remove_auditlog_reports_aud_entity__98d39b_idx_and_more.py`
- **对比 / Comparison**:
  | Feature | Before | After |
  | :--- | :--- | :--- |
  | **Data Structure** | Flat text/mixed fields | Structured `JSONField` (diff/context) |
  | **UI Filter** | Basic inputs, potential overflow | Responsive Grid, Date Range Group |
  | **Readability** | Raw data dumps | Pretty-printed JSON, Color-coded Badges |

### 🏷️ 任务状态与优先级标准化 / Task Status & Priority Standardization
- **Commit**: `268cde8`, `ed484ec`
- **Author**: XueZhang
- **Type**: Feature
- **变更详情 / Details**:
  - **Status**: 废弃旧的状态定义（如 `overdue` 作为状态），转为动态计算。统一状态流转：`todo` -> `in_progress` -> `in_review` -> `done` -> `closed`。
  - **Priority**: 在 UI 中全面启用“优先级”字段（High/Medium/Low），支持在创建、编辑及列表视图中操作。
- **Database**: `0003_task_priority.py` (Related)

### 🔎 全局搜索功能 / Global Search
- **Commit**: `e5a833a`
- **Author**: XueZhang
- **Type**: Feature
- **变更详情 / Details**:
  - 增加全局搜索能力，支持跨项目、任务及日报的内容检索。

---

## 2026-01-26

### 🔔 消息通知系统 / Notification System
- **Commit**: `b9b33d2`
- **Author**: XueZhang
- **Type**: Feature
- **变更详情 / Details**:
  - 实现站内消息通知功能，支持“已读/未读”状态管理及过期自动清理。
- **Database**: `0013_notification_expires_at_...`, `0006_notification...`

### 🛡️ 权限控制体系增强 / Permission Control Enhancement
- **Commit**: `bb3ad8a`, `e3bfe13`, `a0c8ab7`, `3c07766`
- **Author**: XueZhang
- **Type**: Security
- **变更详情 / Details**:
  - 完善基于角色的访问控制 (RBAC)。
  - **Rules**:
    - **Owner**: 拥有项目最高权限。
    - **Manager**: 可管理项目但不可删除 Owner。
    - **Member**: 仅可见相关任务。
  - 增加 UI层面的权限提示与按钮禁用逻辑。

### 👥 协作与多附件支持 / Collaboration & Attachments
- **Commit**: `4b65908` (协作人), `7e79ba0` (多附件)
- **Author**: XueZhang
- **Type**: Feature
- **变更详情 / Details**:
  - **Collaborators**: 任务支持添加多个协作人 (`Task.collaborators` M2M)。
  - **Attachments**: 支持上传多个附件文件 (`TaskAttachment`, `ProjectAttachment`)。
- **Database**: `0008_task_collaborators...`, `0007_projectattachment.py`

### 👤 用户体验优化 / UX Improvements
- **Commit**: `7a0d221` (头像), `612cc24` (UI), `766d77e` (模板)
- **Author**: XueZhang
- **Type**: UX
- **变更详情 / Details**:
  - **Avatar**: 增加用户头像显示（支持图片上传及首字母默认头像）。
  - **UI**: 优化整体页面布局，统一 CSS 变量与设计规范。

---

## 2026-01-25

### ⚡ 性能与底层优化 / Performance & Core
- **Commit**: `309661e`, `f0327b4`
- **Author**: XueZhang
- **Type**: Performance
- **变更详情 / Details**:
  - 数据库查询优化（N+1 问题修复）。
  - 模板渲染性能提升。
  - 数据库字段描述更新 (`4f10e96`)。

---

## 早期版本 / Early Versions

### 🚀 初始化 / Initialization
- **Commit**: `Initial`
- **变更详情 / Details**:
  - 项目脚手架搭建 (Django + Celery + Redis)。
  - 核心模块：`Project`, `Task`, `DailyReport`。
  - 基础认证与管理后台。
- **Database**: `0001_initial.py`
