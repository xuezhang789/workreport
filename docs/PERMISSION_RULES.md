# Permission Control Rules

## Task Management Permissions

### 1. Task Editing Scope
We enforce a strict separation of duties between **Task Owners/Managers** and **Collaborators**.

| Role | Definition | Permissions |
| :--- | :--- | :--- |
| **Superuser** | System Admin | **Full Access**: Can edit all fields, delete tasks, reassign owners. |
| **Project Manager** | User listed in `Project.managers` or `Project.owner` | **Full Access**: Can edit all fields within their projects. |
| **Task Owner** | User listed as `Task.user` | **Full Access**: Can edit title, due date, content, attachments, etc. |
| **Collaborator** | User listed in `Task.collaborators` (but NOT Owner/Manager) | **Restricted Access**: <br> - ✅ Can ONLY update **Status** (e.g., Pending -> In Progress). <br> - ❌ Cannot change Title, Project, Assignee, Collaborators. <br> - ❌ Cannot upload attachments. <br> - ❌ Cannot change Due Date. |
| **Other Members** | Project members not assigned to the task | **Read Only** (if visible) or No Access. |

### 2. Implementation Details

#### Backend (API/View Level)
*   **View**: `admin_task_edit`
*   **Logic**:
    *   Upon `POST` request, the system checks if the user falls into the `is_collaborator_only` category.
    *   If `is_collaborator_only` is True, the system validates that **only** the `status` field is being modified.
    *   Any attempt to modify restricted fields (Title, Project, User, etc.) results in a **403 Forbidden** error.
    *   Restricted fields are forcibly overwritten with their existing database values before saving, ensuring data integrity even if validation is bypassed.

#### Frontend (UI Level)
*   **Template**: `admin_task_form.html`
*   **Logic**:
    *   If `is_collaborator_only` is True:
        *   An alert banner is displayed: *"As a collaborator, you can only update the status."*
        *   Restricted input fields (Title, Project, User, Due Date, etc.) are set to `disabled` and `readonly`.
        *   The "Smart Template" and "File Upload" sections are hidden.
        *   Only the **Status** dropdown and **Task Description** (Content) remain visible.

### 3. Verification
Run the permission test suite to verify these rules:
```bash
python3 manage.py test reports.tests.test_permission_control
```

---

## Project Management Permissions

### 1. Project Editing Scope
We differentiate between **Superusers**, **Project Owners**, and **Project Managers** regarding critical project attributes.

| Role | Definition | Permissions |
| :--- | :--- | :--- |
| **Superuser** | System Admin (`is_superuser=True`) | **Full Access**: Can edit all project fields including Owner and Managers. |
| **Project Owner** | User listed as `Project.owner` | **High Access**: <br> - ✅ Can edit Project Name, Description, Members, Managers, Dates, Status. <br> - ❌ Cannot change **Project Owner** (Self-assignment protection). |
| **Project Manager** | User listed in `Project.managers` | **Standard Access**: <br> - ✅ Can edit Project Name, Description, Members, Dates, Status. <br> - ❌ Cannot change **Project Owner**. <br> - ❌ Cannot change **Project Managers**. |

### 2. Implementation Details

#### Backend (View Level)
*   **View**: `project_edit` in `reports/views.py`
*   **Logic**:
    *   Determines user role (`is_superuser`, `is_owner`).
    *   Sets boolean flags: `can_edit_owner` and `can_edit_managers`.
    *   In `POST` processing, forcibly disables restricted fields on the form instance (`form.fields['field'].disabled = True`). This causes Django to ignore any submitted data for these fields and use the initial database value, effectively preventing unauthorized changes even if the UI is bypassed.

#### Frontend (UI Level)
*   **Template**: `reports/project_form.html`
*   **Logic**:
    *   If `can_edit_owner` is False:
        *   The Owner search input is replaced with a disabled, read-only input showing the current owner's name.
        *   The actual form field is rendered as a hidden disabled element.
    *   If `can_edit_managers` is False:
        *   The Manager multi-select widget is replaced with a static list of badges showing current managers.
        *   The interaction controls (search, checkboxes) are hidden.

### 3. Verification
Run the project permission test suite:
```bash
python3 manage.py test reports.tests.test_project_permissions
```
