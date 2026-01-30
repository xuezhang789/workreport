import logging
from django.utils import timezone
from django.conf import settings
from core.models import SystemSetting
from core.constants import TaskStatus, TaskCategory
from tasks.services.sla import calculate_sla_info, get_sla_hours, get_sla_thresholds

logger = logging.getLogger(__name__)

class TaskExportService:
    """
    Service to handle task export logic, ensuring consistency across different export views.
    """

    HEADER = [
        "ID", 
        "标题 / Title", 
        "项目 / Project", 
        "分类 / Category",
        "状态 / Status", 
        "优先级 / Priority", 
        "负责人 / Assignee", 
        "协作人 / Collaborators", 
        "截止时间 / Due Date", 
        "完成时间 / Completed At", 
        "创建时间 / Created At", 
        "SLA 状态 / SLA Status",
        "SLA 剩余(h) / SLA Remaining(h)",
        "URL", 
        "内容 / Content"
    ]

    @staticmethod
    def get_header():
        return TaskExportService.HEADER

    @staticmethod
    def get_export_rows(tasks):
        """
        Generator that yields rows for the CSV export.
        """
        # Pre-fetch SLA settings once
        cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
        sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
        
        cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
        sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
        
        for task in tasks:
            yield TaskExportService._format_task_row(task, sla_hours_val, sla_thresholds_val)

    @staticmethod
    def _format_task_row(task, sla_hours_val, sla_thresholds_val):
        # Calculate SLA
        sla_info = calculate_sla_info(task, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
        sla_status_display = sla_info.get('status', 'normal')
        if sla_info.get('paused'):
            sla_status_display += " (Paused)"
            
        remaining = sla_info.get('remaining_hours')
        remaining_str = f"{remaining:.1f}" if remaining is not None else ""

        # Format Dates
        due_at = timezone.localtime(task.due_at).strftime('%Y-%m-%d %H:%M:%S') if task.due_at else ''
        completed_at = timezone.localtime(task.completed_at).strftime('%Y-%m-%d %H:%M:%S') if task.completed_at else ''
        created_at = timezone.localtime(task.created_at).strftime('%Y-%m-%d %H:%M:%S')

        # Collaborators
        collabs = ", ".join([u.get_full_name() or u.username for u in task.collaborators.all()])

        return [
            str(task.id),
            task.title,
            task.project.name,
            task.get_category_display(), # Added Category
            task.get_status_display(),
            task.get_priority_display(),
            task.user.get_full_name() or task.user.username,
            collabs,
            due_at,
            completed_at,
            created_at,
            sla_status_display, # Added SLA Status
            remaining_str,      # Added SLA Remaining
            task.url or '',
            task.content or '',
        ]
