
from django.core.cache import cache
from django.db.models import Q
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport
from core.services.rbac import RBACService

def _get_projects_by_permission(user, permission_code):
    """
    内部辅助函数：获取用户拥有特定 RBAC 权限的所有项目查询集。
    
    Args:
        user (User): 用户对象
        permission_code (str): 权限代码 (如 'project.view')
        
    Returns:
        QuerySet: Project 对象的查询集。
                  如果用户未登录，返回空查询集。
                  如果用户拥有全局该权限，返回所有活跃项目。
                  否则返回具有该权限的特定项目集合。
    """
    if not user.is_authenticated:
        return Project.objects.none()
    
    if user.is_superuser:
        return Project.objects.filter(is_active=True)
        
    scopes = RBACService.get_scopes_with_permission(user, permission_code)
    
    # 如果 scopes 中包含 None 或空字符串，表示拥有全局权限
    if None in scopes or '' in scopes:
        return Project.objects.filter(is_active=True)
        
    # 解析 scope 字符串 (格式: 'project:123') 提取项目 ID
    project_ids = []
    for s in scopes:
        if s and s.startswith('project:'):
            try:
                pid = int(s.split(':')[1])
                project_ids.append(pid)
            except (ValueError, IndexError):
                continue
                
    return Project.objects.filter(id__in=project_ids, is_active=True)

def get_accessible_projects(user):
    """
    获取用户有权访问（查看权限）的项目列表。
    
    该函数使用了缓存机制来提高性能。
    缓存键: accessible_projects_ids:{user_id}
    缓存时间: 300秒 (5分钟)
    
    Args:
        user (User): 用户对象
        
    Returns:
        QuerySet: 用户可查看的 Project 查询集
    """
    if not user.is_authenticated:
        return Project.objects.none()

    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    cache_key = f"accessible_projects_ids:{user.id}"
    cached_ids = cache.get(cache_key)

    if cached_ids is not None:
        return Project.objects.filter(id__in=cached_ids, is_active=True)

    # 纯 RBAC 权限检查
    # 获取拥有 'project.view' 权限的项目
    final_qs = _get_projects_by_permission(user, 'project.view')
    
    # 缓存结果 ID 列表
    ids = list(final_qs.values_list('id', flat=True))
    cache.set(cache_key, ids, 300) # 缓存5分钟
    
    return Project.objects.filter(id__in=ids)

def can_manage_project(user, project):
    """
    检查用户是否拥有特定项目的管理/编辑权限。
    
    该函数使用了缓存机制。
    缓存键: can_manage_project:{user_id}:{project_id}
    缓存时间: 300秒
    
    Args:
        user (User): 用户对象
        project (Project): 项目对象
        
    Returns:
        bool: 如果有管理权限返回 True，否则 False
    """
    if not user.is_authenticated:
        return False
        
    if user.is_superuser:
        return True
        
    # 优先检查缓存
    cache_key = f"can_manage_project:{user.id}:{project.id}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    # RBAC 权限检查
    scope = f"project:{project.id}"
    result = RBACService.has_permission(user, 'project.manage', scope=scope)
    
    cache.set(cache_key, result, 300)
    return result

def get_manageable_projects(user):
    """
    获取用户可以管理（编辑/更新）的项目查询集。
    
    Args:
        user (User): 用户对象
        
    Returns:
        QuerySet: 用户可管理的 Project 查询集
    """
    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    return _get_projects_by_permission(user, 'project.manage')

def get_accessible_tasks(user):
    """
    获取用户可访问的所有任务查询集。
    逻辑：只要用户能访问该任务所属的项目，就能访问该任务。
    
    Args:
        user (User): 用户对象
        
    Returns:
        QuerySet: Task 查询集
    """
    if not user.is_authenticated:
        return Task.objects.none()
    
    if user.is_superuser:
        return Task.objects.all()

    projects = get_accessible_projects(user)
    return Task.objects.filter(project__in=projects).distinct()

def get_accessible_reports(user):
    """
    获取用户可见的日报查询集。
    逻辑：日报关联的项目如果用户可访问，则日报可见。
    
    Args:
        user (User): 用户对象
        
    Returns:
        QuerySet: DailyReport 查询集
    """
    if not user.is_authenticated:
        return DailyReport.objects.none()
    
    if user.is_superuser:
        return DailyReport.objects.all()

    projects = get_accessible_projects(user)
    
    # 筛选关联了用户可访问项目的日报
    return DailyReport.objects.filter(projects__in=projects).distinct()

def clear_project_permission_cache(user, project=None):
    """
    清除用户的项目权限相关缓存。
    
    在用户权限变更、项目成员变更时应调用此函数。
    
    Args:
        user (User): 用户对象
        project (Project, optional): 特定项目对象。如果提供，将清除针对该项目的管理权限缓存。
    """
    if not user:
        return
        
    # 清除可访问项目列表缓存
    cache.delete(f"accessible_projects_ids:{user.id}")
    
    # 清除特定项目权限缓存
    if project:
        cache.delete(f"can_manage_project:{user.id}:{project.id}")
    else:
        # 如果未指定项目，仅依靠 TTL 过期或后续特定调用
        pass
