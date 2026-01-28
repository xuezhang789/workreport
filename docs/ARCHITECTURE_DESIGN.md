# Architecture Design & Refactoring Plan

## 1. Overview
This document outlines the plan to refactor the monolithic `reports` application into a modular, domain-driven architecture. The goal is to improve maintainability, scalability, and separation of concerns by splitting the codebase into distinct applications: `core`, `projects`, `tasks`, `work_logs` (daily reports), and `audit`.

## 2. New Architecture

### 2.1 App Structure
The functionality will be distributed as follows:

| New App | Responsibilities | Key Models | Dependencies |
| :--- | :--- | :--- | :--- |
| **`core`** | User management, system-wide settings, notifications, generic utilities. | `Profile`, `SystemSetting`, `Notification`, `UserPreference`, `PermissionMatrix`, `ExportJob` | None |
| **`projects`** | Project lifecycle, phases, configuration, attachments, permissions. | `Project`, `ProjectPhaseConfig`, `ProjectPhaseChangeLog`, `ProjectAttachment`, `ProjectMemberPermission`, `ReminderRule` | `core` |
| **`tasks`** | Task management, comments, attachments, SLA tracking. | `Task`, `TaskComment`, `TaskAttachment`, `TaskSlaTimer`, `TaskHistory`, `TaskTemplateVersion` | `core`, `projects` |
| **`work_logs`** | Daily reporting, report templates, miss tracking. | `DailyReport`, `ReportMiss`, `ReportTemplateVersion`, `RoleTemplate` | `core`, `projects` |
| **`audit`** | System-wide audit logging. | `AuditLog` | `core`, `projects`, `tasks` |

### 2.2 Data Flow & Interfaces
*   **Service Layer Pattern**: Each app will expose a `services.py` or `api.py` module for inter-app communication, minimizing direct model imports in views of other apps.
*   **API**: RESTful APIs (Django Views/DRF) will be grouped by domain (e.g., `/api/projects/`, `/api/tasks/`).
*   **Events**: Signals will be used for decoupled actions (e.g., Task completion -> Audit Log).

## 3. Database Schema Changes
The database tables will be renamed to reflect the new app structure.

*   `reports_profile` -> `core_profile`
*   `reports_project` -> `projects_project`
*   `reports_task` -> `tasks_task`
*   `reports_dailyreport` -> `work_logs_dailyreport`
*   ...and so on.

## 4. Migration Strategy

### 4.1 Phase 1: Preparation (Completed)
1.  Created new Django apps (`core`, `projects`, `tasks`, `work_logs`, `audit`).
2.  Defined models in new apps matching the old structure.
3.  Generated migrations and created new tables (`python manage.py migrate`).

### 4.2 Phase 2: Data Migration (Completed)
1.  Developed `migrate_legacy_data` management command.
2.  Successfully executed data migration, copying all records from `reports_*` tables to new app tables.
3.  Verified data integrity (counts match).

### 4.3 Phase 3: Code Switchover (Next Steps)
1.  Update `urls.py` to route API calls to new views.
2.  Refactor Views to use new Models.
3.  Verify using the test suite.

### 4.4 Phase 4: Cleanup
1.  Archive/Delete old `reports` app code.
2.  Drop old `reports_*` tables after backup.

## 5. Rollback Plan
*   The old tables (`reports_*`) are preserved until Phase 4.
*   If new code fails, revert to using the old `reports` app models and views.
*   Data written to new tables during the transition period would need to be sync-backed if we rollback, but for the initial cutover, we assume a maintenance window or parallel write strategy if needed. (For simplicity, we assume a cutover maintenance window).
