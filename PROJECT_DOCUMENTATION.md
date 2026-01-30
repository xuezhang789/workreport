
# WorkReport Project Documentation

## 1. Project Overview
WorkReport is a comprehensive project management and reporting system designed to streamline team collaboration, task tracking, and daily work reporting. It integrates Project Management (PM), Task Management, Daily Reporting, and Audit Logging into a unified platform.

## 2. Architecture & Tech Stack
- **Backend Framework**: Django 4.2 (Python 3.10+)
- **Database**: MySQL / SQLite (Dev)
- **Frontend**: Django Templates + HTML/CSS/JS (Bootstrap/Tailwind-like styles)
- **Asynchronous**: Django Channels (Redis) for real-time features (planned)
- **Email**: SMTP for notifications

## 3. Core Modules

### 3.1 User & Permissions (`core`)
- **User Model**: Standard Django User extended with `Profile`.
- **Roles**: 
    - **Superuser**: Full access.
    - **Manager/PM**: Can manage assigned projects.
    - **Member**: Can view/edit assigned tasks and reports.
- **Permission Matrix**: Configurable RBAC system (Model: `PermissionMatrix`).

### 3.2 Project Management (`projects`)
- **Projects**: Core entity. Tracks code, owner, members, managers, timeline.
- **Phases**: Configurable lifecycle phases (e.g., Planning, Dev, QA, Release).
    - **Phase Config**: Define phase names and progress %.
    - **Phase History**: Audit log of phase transitions.
- **Attachments**: File management per project.

### 3.3 Task Management (`tasks`)
- **Tasks**: Work units linked to Projects.
- **SLA Tracking**: 
    - Monitors task due dates.
    - SLA Status: On Track, Amber (Warning), Red (Breached).
    - Pause logic for "Blocked" states.
- **Comments & Attachments**: Collaboration tools.
- **Audit**: All changes are logged (Status, Priority, Assignee).

### 3.4 Reporting (`reports` & `work_logs`)
- **Daily Reports**: Users submit daily work logs (Today, Tomorrow, Risks).
- **Templates**: Role-based templates (Dev, QA, PM) for standardized reporting.
- **Stats**: Productivity analytics (SLA rates, Task completion).
- **Notifications**: Email and in-app alerts for overdue tasks/reports.

### 3.5 Audit & Security (`audit`)
- **AuditLog**: Centralized immutable log of all critical actions.
- **Coverage**: Project changes, Task updates, File uploads.
- **Features**: 
    - JSON-based diff storage (Old vs New values).
    - Idempotency checks to prevent duplicate logs.
    - Operator tracking (IP, User).

## 4. Database Schema

### App: projects
| Model | Description |
| --- | --- |
| **Project** | Main project entity. |
| **ProjectPhaseConfig** | Defines workflow stages. |
| **ProjectPhaseChangeLog** | History of phase transitions. |
| **ProjectMemberPermission** | Fine-grained per-project permissions. |

### App: tasks
| Model | Description |
| --- | --- |
| **Task** | Task entity with status, priority, due_date. |
| **TaskSlaTimer** | Tracks time spent/paused for SLA calculations. |
| **TaskComment** | Discussion thread. |

### App: work_logs (Reports)
| Model | Description |
| --- | --- |
| **DailyReport** | Structured daily input. |
| **ReportTemplateVersion** | Versioned templates for reports. |
| **ReminderRule** | Rules for sending "Missing Report" notifications. |

### App: audit
| Model | Description |
| --- | --- |
| **AuditLog** | Universal audit trail. |

## 5. API & Views Structure
- **Admin**: Standard Django Admin for configuration.
- **Web Interface**:
    - `/projects/`: Project dashboard.
    - `/tasks/`: Task board/list.
    - `/reports/`: Reporting workbench.
- **Internal APIs**:
    - `/projects/api/search/`: JSON endpoint for project autocomplete.
    - `/tasks/api/<id>/`: Task details for modals.

## 6. Security & Configuration
- **Environment Variables**: All secrets (`SECRET_KEY`, `DB_PASS`) loaded from `.env`.
- **Debug Mode**: Disabled in production via env.
- **Access Control**: Decorator-based (`@login_required`) and Mixin-based access control.

## 7. Known Issues & Future Work
- **Performance**: Large task lists need optimized pagination (partially implemented).
- **Frontend**: Move to React/Vue for more interactive boards (Future).
- **Search**: Currently DB-based `icontains`. Consider ElasticSearch for scale.

