from .admin_views import (
    admin_task_list,
    admin_task_bulk_action,
    admin_task_export,
    sla_settings,
    admin_task_stats,
    admin_task_stats_export,
    admin_task_create,
    admin_task_edit
)
from .user_views import (
    task_upload_attachment,
    task_delete_attachment,
    task_list,
    task_export,
    task_export_selected,
    task_complete,
    task_bulk_action,
    task_view,
    task_history
)
from .api_views import api_task_detail
