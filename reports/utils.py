
from django.core.cache import cache
from django.db.models import Q
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport
from core.services.rbac import RBACService

def _get_rbac_project_ids(user, permission_code):
    """
    内部辅助函数：获取用户拥有特定 RBAC 权限的项目 ID 列表。
    
    Returns:
        tuple: (is_global, project_ids)
        - is_global (bool): 是否拥有全局权限
        - project_ids (list): 项目 ID 列表 (当 is_global=False 时)
    """
    if not user.is_authenticated:
        return False, []
    
    if user.is_superuser:
        return True, []
        
    cache_key = f"rbac_project_ids:{user.id}:{permission_code}"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    scopes = RBACService.get_scopes_with_permission(user, permission_code)
    
    # 如果 scopes 中包含 None 或空字符串，表示拥有全局权限
    if None in scopes or '' in scopes:
        result = (True, [])
        cache.set(cache_key, result, 300)
        return result
        
    # 解析 scope 字符串 (格式: 'project:123') 提取项目 ID
    project_ids = []
    for s in scopes:
        if s and s.startswith('project:'):
            try:
                pid = int(s.split(':')[1])
                project_ids.append(pid)
            except (ValueError, IndexError):
                continue
    
    result = (False, project_ids)
    cache.set(cache_key, result, 300)
    return result

def get_accessible_projects(user):
    """
    获取用户有权访问（查看权限）的项目列表。
    
    优化策略：
    不再缓存所有可访问项目的 ID 列表（因为可能很大且难以失效）。
    改为缓存 RBAC 权限计算出的 ID 列表（相对稳定且较小）。
    返回的 QuerySet 使用 Q 对象组合查询，利用数据库索引进行过滤。
    
    Args:
        user (User): 用户对象
        
    Returns:
        QuerySet: 用户可查看的 Project 查询集
    """
    if not user.is_authenticated:
        return Project.objects.none()

    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    # 1. RBAC 权限检查
    is_global, rbac_ids = _get_rbac_project_ids(user, 'project.view')
    
    if is_global:
        return Project.objects.filter(is_active=True)
    
    # 2. 组合查询：RBAC IDs OR 直接关联 (Members, Owner, Managers)
    # 利用 distinct() 确保不重复
    return Project.objects.filter(
        Q(id__in=rbac_ids) | 
        Q(members=user) | 
        Q(owner=user) | 
        Q(managers=user),
        is_active=True
    ).distinct()

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

    # 1. 直接关联 (Owner, Managers)
    if project.owner_id == user.id or project.managers.filter(pk=user.pk).exists():
        cache.set(cache_key, True, 300)
        return True

    # 2. RBAC 权限检查
    scope = f"project:{project.id}"
    result = RBACService.has_permission(user, 'project.manage', scope=scope)
    
    cache.set(cache_key, result, 300)
    return result

def get_manageable_projects(user):
    """
    获取用户可以管理（编辑/更新）的项目查询集。
    
    优化：使用 Q 对象组合查询，减少全量 ID 列表的内存占用和缓存压力。
    
    Args:
        user (User): 用户对象
        
    Returns:
        QuerySet: 用户可管理的 Project 查询集
    """
    if not user.is_authenticated:
        return Project.objects.none()

    if user.is_superuser:
        return Project.objects.filter(is_active=True)

    # 1. RBAC 权限
    is_global, rbac_ids = _get_rbac_project_ids(user, 'project.manage')
    
    if is_global:
        return Project.objects.filter(is_active=True)

    # 2. 组合查询：RBAC IDs OR 直接关联 (Owner, Managers)
    return Project.objects.filter(
        Q(id__in=rbac_ids) | 
        Q(owner=user) | 
        Q(managers=user),
        is_active=True
    ).distinct()

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
        
    # 清除 RBAC ID 列表缓存 (无法精确知道是 view 还是 manage，所以可能需要全部清除或依赖 TTL)
    # 由于 rbac_project_ids 依赖 permission_code，我们这里主要清除 can_manage_project 缓存
    # RBAC 缓存主要由 RBACService 管理
    
    # 清除旧的 ID 列表缓存（为了兼容性）
    cache.delete(f"accessible_projects_ids:{user.id}")
    cache.delete(f"manageable_projects_ids:{user.id}")
    
    # 清除新的 RBAC 缓存 (View 和 Manage)
    cache.delete(f"rbac_project_ids:{user.id}:project.view")
    cache.delete(f"rbac_project_ids:{user.id}:project.manage")
    
    # 清除特定项目权限缓存
    if project:
        cache.delete(f"can_manage_project:{user.id}:{project.id}")
