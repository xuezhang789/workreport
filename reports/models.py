"""Compatibility model exports for legacy callers.

New application code must import models from their owning Django app.
"""

from core.models import (
    Profile,
    SystemSetting,
    ExportJob,
    UserPreference,
    Notification,
    default_export_expiry
)
from projects.models import (
    ProjectPhaseConfig,
    Project,
    ProjectPhaseChangeLog,
    ProjectAttachment,
    ProjectMemberPermission
)
from tasks.models import (
    Task,
    TaskComment,
    TaskAttachment,
    TaskSlaTimer,
    TaskTemplateVersion
)
from work_logs.models import (
    ReminderRule,
    ReportMiss,
    DailyReport,
    RoleTemplate,
    ReportTemplateVersion
)
from audit.models import (
    AuditLog,
    TaskHistory
)

__all__ = [
    'Profile', 'SystemSetting', 'ExportJob', 'UserPreference', 'Notification',
    'default_export_expiry', 'ProjectPhaseConfig', 'Project',
    'ProjectPhaseChangeLog', 'ProjectAttachment', 'ProjectMemberPermission',
    'Task', 'TaskComment', 'TaskAttachment', 'TaskSlaTimer',
    'TaskTemplateVersion', 'ReminderRule', 'ReportMiss', 'DailyReport',
    'RoleTemplate', 'ReportTemplateVersion', 'AuditLog', 'TaskHistory',
]
