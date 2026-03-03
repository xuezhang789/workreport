import logging
from datetime import timedelta
from django.db.models import Q
from django.utils import timezone
from django.core.paginator import Paginator
from django.contrib.auth import get_user_model
from tasks.models import Task
from core.models import SystemSetting
from core.constants import TaskStatus, TaskCategory
from tasks.services.sla import calculate_sla_info, get_sla_hours, get_sla_thresholds
from reports.utils import get_accessible_projects

logger = logging.getLogger(__name__)

class TaskAdminService:
    @staticmethod
    def get_admin_task_list_context(user, params, full_path):
        """
        Service method to retrieve context for the admin task list view.
        Encapsulates filtering, sorting, pagination, and SLA calculation logic.
        """
        # 1. 权限检查与基础查询集
        accessible_projects = get_accessible_projects(user)
        if not accessible_projects.exists():
            return {'error': "需要相关项目权限 / Project access required"}

        status = (params.get('status') or '').strip()
        category = (params.get('category') or '').strip()
        priority = (params.get('priority') or '').strip()
        project_id = params.get('project')
        user_id = params.get('user')
        q = (params.get('q') or '').strip()
        hot = params.get('hot') == '1'
        sort_by = params.get('sort', '-created_at')

        # 优化：为头像渲染选择关联的 profile 和 preferences
        tasks_qs = Task.objects.select_related(
            'project', 'user', 'sla_timer', 'user__profile', 'user__preferences'
        ).prefetch_related('collaborators', 'collaborators__profile', 'collaborators__preferences')
        
        # 立即按可访问项目过滤
        tasks_qs = tasks_qs.filter(project__in=accessible_projects)
        
        # 2. SLA 配置预取
        cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
        sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
        
        cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
        sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
        
        now = timezone.now()
        default_sla_hours = get_sla_hours(system_setting_value=sla_hours_val)
        
        # 优化：计算即将到期的任务 ID 集合
        due_soon_ids = set(tasks_qs.filter(
            status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW],
            due_at__gt=now,
            due_at__lte=now + timedelta(hours=default_sla_hours)
        ).values_list('id', flat=True))

        # 3. 应用过滤器
        if status in dict(Task.STATUS_CHOICES):
            tasks_qs = tasks_qs.filter(status=status)
        if category in dict(Task.CATEGORY_CHOICES):
            tasks_qs = tasks_qs.filter(category=category)
        if priority in dict(Task.PRIORITY_CHOICES):
            tasks_qs = tasks_qs.filter(priority=priority)
        if project_id and project_id.isdigit():
            pid = int(project_id)
            if accessible_projects.filter(id=pid).exists():
                tasks_qs = tasks_qs.filter(project_id=pid)
            else:
                tasks_qs = tasks_qs.none()
        if user_id and user_id.isdigit():
            tasks_qs = tasks_qs.filter(user_id=int(user_id))
        if q:
            tasks_qs = tasks_qs.filter(Q(title__icontains=q) | Q(content__icontains=q))

        # 4. 排序与分页 (包含 Hot 逻辑)
        per_page = 20
        try:
            per_page_param = int(params.get('per_page', 20))
            if per_page_param in [10, 20, 50, 100]:
                per_page = per_page_param
        except (ValueError, TypeError):
            pass

        page_obj = None
        
        if hot:
            # Hot 模式：数据库层面过滤
            amber_hours = get_sla_thresholds(sla_thresholds_val).get('amber', 4)
            cutoff_time = now + timedelta(hours=amber_hours)
            
            tasks_qs = tasks_qs.exclude(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).filter(
                due_at__isnull=False,
                due_at__lt=cutoff_time
            ).order_by('due_at', '-created_at')
            
            paginator = Paginator(tasks_qs, per_page)
            page_obj = paginator.get_page(params.get('page'))
            
            # 计算 SLA
            for t in page_obj:
                t.is_due_soon = True
                t.sla_info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
                
        else:
            # 标准模式
            allowed_sorts = {
                'created_at': 'created_at',
                '-created_at': '-created_at',
                'priority': 'priority',
                '-priority': '-priority',
                'status': 'status',
                '-status': '-status',
                'due_at': 'due_at',
                '-due_at': '-due_at',
                'title': 'title',
                '-title': '-title',
            }
            sort_field = allowed_sorts.get(sort_by, '-created_at')
            tasks_qs = tasks_qs.order_by(sort_field)

            paginator = Paginator(tasks_qs, per_page)
            page_obj = paginator.get_page(params.get('page'))
            
            for t in page_obj:
                t.is_due_soon = t.id in due_soon_ids
                t.sla_info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)

        # 5. 准备筛选选项
        User = get_user_model()
        project_choices = accessible_projects.order_by('name').only('id', 'name', 'code')[:100]
        
        if user.is_superuser:
            user_objs = User.objects.filter(is_active=True).order_by('username').only('id', 'username', 'first_name', 'last_name')[:100]
        else:
            relevant_user_ids = set(User.objects.filter(
                Q(project_memberships__in=accessible_projects) |
                Q(managed_projects__in=accessible_projects) |
                Q(owned_projects__in=accessible_projects)
            ).values_list('id', flat=True))
            user_objs = User.objects.filter(id__in=relevant_user_ids).order_by('username').only('id', 'username', 'first_name', 'last_name')[:100]

        return {
            'tasks': page_obj,
            'page_obj': page_obj,
            'per_page': per_page,
            'status': status,
            'category': category,
            'priority': priority,
            'q': q,
            'project_id': int(project_id) if project_id and project_id.isdigit() else '',
            'user_id': int(user_id) if user_id and user_id.isdigit() else '',
            'hot': hot,
            'sort_by': sort_by,
            'projects': project_choices,
            'users': user_objs,
            'task_status_choices': Task.STATUS_CHOICES,
            'task_category_choices': Task.CATEGORY_CHOICES,
            'task_priority_choices': Task.PRIORITY_CHOICES,
            'due_soon_ids': due_soon_ids,
            'sla_config_hours': default_sla_hours,
            'redirect_to': full_path,
            'sla_thresholds': get_sla_thresholds(system_setting_value=sla_thresholds_val),
        }
