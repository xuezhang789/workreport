# 已弃用：此文件保留是为了与旧迁移向后兼容。
# 请直接从各自的应用程序导入模型：
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
