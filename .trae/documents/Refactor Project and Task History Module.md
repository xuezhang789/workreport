# Project & Task Change History Refactoring Plan

## 1. Analysis of Current Implementation
- **Architecture**: Unified `AuditLog` model (in `audit/models.py`) stores changes.
- **Capture Mechanism**:
  - `audit/signals.py` uses `pre_save`/`post_save` to calculate diffs automatically.
  - `m2m_changed` signals handle relationship changes (members, managers, collaborators).
  - `AuditMiddleware` captures user context.
- **Storage**: JSONField `details` stores diffs (`{'diff': {field: {old, new}}}`).
- **Services**:
  - `AuditLogService` (in `audit/services.py`) handles querying and formatting.
  - `AuditService` (in `reports/services/audit_service.py`) provides manual logging (seems redundant/legacy?).
- **UI/UX Issues**:
  - **Readability**: Raw diffs might be hard to read (e.g., IDs instead of names, technical field names).
  - **Structure**: Linear list of logs might get cluttered.
  - **Filtering**: Basic filtering exists but could be more intuitive (e.g., "Only Status Changes").
  - **Mobile**: Tables/Lists might not be responsive enough.

## 2. Redesign Strategy
- **Data Structure**: Keep `AuditLog` but enhance `details` JSON structure for better UI rendering (ensure `verbose_name`, `user_friendly_value`).
- **UI Improvements**:
  - **Timeline View**: A vertical timeline component is better than a table for history.
  - **Grouped Changes**: Group multiple field changes from one save action into a single timeline entry.
  - **Visual Diffs**: Use color coding (Red/Green) for Old/New values.
  - **Smart Filters**: "Key Events" (Status, Priority, Phase) vs "All Events".
- **Mobile Optimization**: Responsive timeline layout.

## 3. Implementation Plan

### Phase 1: Enhanced Data Capture & Storage (Backend)
1.  **Refine Signals (`audit/signals.py`)**:
    - Ensure `verbose_name` is always captured (already partially done, review robustness).
    - Improve value formatting (FKs to names, Choices to labels).
    - Ensure M2M changes are readable.
2.  **Unify Services**:
    - Deprecate `reports/services/audit_service.py` if possible or align it with `audit/services.py`.
    - Enhance `AuditLogService.format_log_entry` to support "Grouped" rendering for the Timeline.

### Phase 2: UI/UX Redesign (Frontend)
1.  **New Timeline Component**:
    - Create a reusable Django template partial `audit/timeline.html`.
    - Styles for "Timeline Item", "Actor Avatar", "Timestamp", "Change Card".
2.  **Project History Page**:
    - Update `projects/templates/projects/project_history.html` (or equivalent) to use the new timeline.
    - Add "Smart Filters" (checkboxes for: Status, Members, Dates).
3.  **Task History Tab**:
    - Update Task Detail view to use the same timeline component.

### Phase 3: Testing & Verification
1.  **Unit Tests**:
    - Test signal capturing for various field types (Text, Choice, FK, M2M).
    - Test `AuditLogService` filtering and formatting.
2.  **User Acceptance**:
    - Verify UI responsiveness.
    - Verify readability of changes.

## 4. Key Deliverables
- Refactored `audit/signals.py` for better data quality.
- Enhanced `AuditLogService` for timeline-ready data.
- New `timeline.html` template.
- Updated Project/Task views to use the new system.
