# Permission System Design & Optimization

## 1. Overview
The WorkReport permission system has been optimized to use a centralized **Role-Based Access Control (RBAC)** model with scoped permissions, caching, and unified frontend/backend checks. This ensures security, performance, and consistency across the application.

## 2. Core Concepts

### 2.1 RBAC Model
The system uses four core models (defined in `core.models`):
- **Permission**: Atomic capability (e.g., `project.view`, `task.create`).
- **Role**: A collection of permissions (e.g., `Manager`, `Member`). Roles can inherit from other roles.
- **UserRole**: Assigns a Role to a User within a specific **Scope**.
- **Scope**: Defines the boundary of the permission (e.g., `project:1`, `global`).

### 2.2 Hybrid Approach
To maintain backward compatibility and support legacy logic (Owner/Manager fields on Project model), the system uses a hybrid approach in `reports.utils`:
- **Superuser**: Has full access.
- **Owner**: Implicit full access to their projects.
- **Manager (Legacy)**: Implicit management access via `project.managers` M2M field.
- **RBAC**: Explicit granular access via `UserRole`.

## 3. Implementation Details

### 3.1 Backend Services
- **`core.services.rbac.RBACService`**:
  - `has_permission(user, code, scope)`: Checks if user has permission.
  - `get_user_permissions(user, scope)`: Returns all permission codes for a user in a scope.
  - `assign_role/remove_role`: Manages user roles.
  - **Caching**: Uses Django cache (Redis/LocMem) to store user permissions for 1 hour (`CACHE_TIMEOUT`). Keys are namespaced by `rbac:user:{id}:scope:{scope}`.

- **`reports.utils` (Centralized Access)**:
  - `get_accessible_projects(user)`: Returns QuerySet of projects visible to user.
  - `can_manage_project(user, project)`: Boolean check for management rights (Superuser OR Owner OR Manager OR `project.manage` permission).
  - `get_manageable_projects(user)`: Returns QuerySet of projects manageable by user.

### 3.2 Frontend Integration
- **Template Tags (`core.templatetags.permission_tags`)**:
  - `{% can_manage_project project as can_manage %}`: Checks management permission.
  - `{% has_perm 'code' scope='...' as result %}`: Checks granular permission.

### 3.3 Caching Strategy
- **Read**: Permissions are cached on first access per request/scope.
- **Write**: 
  - Assigning/Removing roles clears the specific user's cache.
  - Modifying Role permissions clears cache for **all users** with that role (expensive operation, done rarely).

## 4. Usage Guide

### 4.1 Checking Permissions in Views
```python
from reports.utils import can_manage_project, get_accessible_projects

def my_view(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    
    # Check if user can manage
    if not can_manage_project(request.user, project):
        return HttpResponseForbidden()
        
    # Filter querysets
    projects = get_accessible_projects(request.user)
```

### 4.2 Checking Permissions in Templates
```html
{% load permission_tags %}

{% can_manage_project project as can_manage %}
{% if can_manage %}
    <a href="...">Edit Project</a>
{% endif %}
```

### 4.3 Adding New Permissions
1. Define the permission code (e.g., `report.export`).
2. Create it via Django Admin or data migration:
   ```python
   RBACService.create_permission('Export Reports', 'report.export', 'report')
   ```
3. Assign to roles via Admin.

### 4.4 User Search Policy
- **Global Managers**: Can search all users.
- **Project Owners/Managers**: Can search all users (to add new members) in global context.
- **Task Assignment (Scoped)**: When `project_id` is provided (e.g., Create Task), search is strictly limited to **existing project members** (Owner, Managers, Members).
- **Regular Members**: Can only search users within their accessible projects.
- **API**: `core.views.user_search_api` implements this logic.

## 5. Performance Optimization
- **Bulk Fetching**: `get_manageable_projects` uses optimized queries to fetch IDs in bulk for list views.
- **Lazy Loading**: Permission checks are lazy where possible.
- **Caching**: High-frequency checks (e.g., in loops) hit the cache after the first DB query.

## 6. Migration Status
- **Legacy**: `ProjectAccessMixin` removed.
- **Current**: All core views (`projects`, `tasks`, `reports`) use `reports.utils`.
- **Pending**: granular UI for assigning roles to members (currently relies on Admin or implicit Manager field).
