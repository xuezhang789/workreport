# DEPRECATED: This file is kept for backward compatibility with old migrations.
# Please import models directly from their respective apps:
# - core.models
# - projects.models
# - tasks.models
# - work_logs.models
# - audit.models

from core.models import (
    Profile,
    SystemSetting,
    ExportJob,
    UserPreference,
    Notification,
    PermissionMatrix,
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
