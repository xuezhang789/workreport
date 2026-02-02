import logging
from django.utils import timezone
from django.conf import settings
from core.models import SystemSetting
from core.constants import TaskStatus, TaskCategory
from tasks.services.sla import calculate_sla_info, get_sla_hours, get_sla_thresholds

logger = logging.getLogger(__name__)

class TaskExportService:
    """
    处理任务导出逻辑的服务，确保不同导出视图之间的一致性。
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
        生成器，生成 CSV 导出的行。
        """
        # 预取一次 SLA 设置
        cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
        sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
        
        cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
        sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
        
        for task in tasks:
            yield TaskExportService._format_task_row(task, sla_hours_val, sla_thresholds_val)

    @staticmethod
    def _format_task_row(task, sla_hours_val, sla_thresholds_val):
        # 计算 SLA
        sla_info = calculate_sla_info(task, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
        sla_status_display = sla_info.get('status', 'normal')
        if sla_info.get('paused'):
            sla_status_display += " (Paused)"
            
        remaining = sla_info.get('remaining_hours')
        remaining_str = f"{remaining:.1f}" if remaining is not None else ""

        # 格式化日期
        due_at = timezone.localtime(task.due_at).strftime('%Y-%m-%d %H:%M:%S') if task.due_at else ''
        completed_at = timezone.localtime(task.completed_at).strftime('%Y-%m-%d %H:%M:%S') if task.completed_at else ''
        created_at = timezone.localtime(task.created_at).strftime('%Y-%m-%d %H:%M:%S')

        # 协作者
        collabs = ", ".join([u.get_full_name() or u.username for u in task.collaborators.all()])

        return [
            str(task.id),
            task.title,
            task.project.name,
            task.get_category_display(), # 添加分类
            task.get_status_display(),
            task.get_priority_display(),
            task.user.get_full_name() or task.user.username,
            collabs,
            due_at,
            completed_at,
            created_at,
            sla_status_display, # 添加 SLA 状态
            remaining_str,      # 添加 SLA 剩余时间
            task.url or '',
            task.content or '',
        ]
