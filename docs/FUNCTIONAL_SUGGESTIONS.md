
# Functional Enhancement Suggestions / 功能增强建议

**Date:** 2026-02-04
**Based On:** Codebase Analysis & Enterprise Best Practices

## 1. Real-time Notification Center (WebSockets)
### Context
Currently, the system uses `channels` with `InMemoryChannelLayer` (not prod-ready) or relies on page refreshes/polling for updates. `Notification` model exists but is passive.
### Proposal
Implement a full WebSocket-based notification system using `django-channels` and `Redis`.
### Implementation Path
1.  **Infrastructure**: Replace `InMemoryChannelLayer` with `RedisChannelLayer`.
2.  **Backend**: Create a `NotificationConsumer` that listens to a user-specific group.
3.  **Signals**: On `Task.save()` or `DailyReport.save()`, trigger an async group send to the relevant users.
4.  **Frontend**: Add a WebSocket client in `base_topbar.html` to receive events and update the notification bell badge in real-time.
### Benefits
-   Immediate feedback for task assignments and mentions.
-   Reduced server load (no polling).
### Workload
-   Backend: 2 days
-   Frontend: 1 day

## 2. Advanced Role-Based Access Control (RBAC) UI
### Context
The backend has powerful RBAC models (`Role`, `Permission`, `UserRole`) and logic (`core.services.rbac`), but there is no visible UI for administrators to configure these dynamically. They likely rely on Django Admin or database scripts.
### Proposal
Develop a "System Administration > Permission Management" module.
### Implementation Path
1.  **Role Management View**: CRUD for `Role` model (Create custom roles like "External Auditor").
2.  **Permission Matrix UI**: A grid view mapping Roles to Permissions (checkboxes).
3.  **User Assignment UI**: A view to assign Roles to Users, with "Scope" selection (Global vs Project-specific).
### Benefits
-   Self-service for admins to create custom roles without code changes.
-   Better visibility into who has access to what.
### Workload
-   Full Stack: 3-4 days

## 3. Automated Report Aggregation & Intelligence
### Context
Managers currently read individual reports. The `stats` view provides numbers but not qualitative insights.
### Proposal
Implement an "AI Weekly Summary" or "Project Pulse" feature.
### Implementation Path
1.  **Data Collection**: Celery task runs weekly, collecting all `DailyReport.today_work` and `progress_issues` for a project.
2.  **Processing**: (Optional) Send text to an LLM API (if policy allows) to summarize key achievements and risks. Or use simple NLP (keyword extraction) to highlight "Blocker", "Delay", "Urgent".
3.  **Delivery**: Email the summary to the Project Manager every Monday morning.
### Benefits
-   Saves hours of reading time for managers.
-   Early detection of risks hidden in free-text reports.
### Workload
-   Backend (Celery + Logic): 3 days
-   Integration: 1 day

## 4. Task Dependency & Gantt Chart V2
### Context
The previous `advanced_reporting` module (now removed) contained a basic Gantt chart, but the `Task` model doesn't explicitly store dependencies (Predecessor/Successor), only `project`.
### Proposal
Add explicit dependencies to support Critical Path Analysis.
### Implementation Path
1.  **Model**: Add `dependencies = ManyToManyField('self', symmetrical=False, related_name='blocked_by')` to `Task`.
2.  **Validation**: Prevent circular dependencies on save.
3.  **API**: Update Task APIs to return dependency graph.
4.  **Frontend**: Upgrade the Gantt chart library to render lines between dependent tasks.
### Benefits
-   True project management capability.
-   Auto-calculation of schedule slippage impact.
### Workload
-   Backend: 2 days
-   Frontend: 3 days

## 5. Mobile Progressive Web App (PWA)
### Context
The current UI is responsive but lacks mobile-native feel (offline support, home screen install).
### Proposal
Convert the existing Django templates into a PWA.
### Implementation Path
1.  **Manifest**: Add `manifest.json`.
2.  **Service Worker**: Cache static assets (CSS/JS) and critical read-only API responses (e.g., "My Tasks").
3.  **Offline Mode**: Allow drafting reports offline and syncing when online.
### Benefits
-   Better experience for field workers or commuters.
-   Zero-install mobile app.
### Workload
-   Frontend: 2 days
