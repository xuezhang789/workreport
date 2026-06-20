from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete
from django.dispatch import receiver

from core.models import Role, RolePermission, UserRole
from core.services.permission_cache import invalidate_user_permission_cache
from core.services.search_index import delete_instance, schedule_sync_instance
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport


def _role_and_descendant_ids(role_id):
    role_ids = {role_id}
    frontier = {role_id}
    while frontier:
        children = set(Role.objects.filter(parent_id__in=frontier).values_list('id', flat=True))
        frontier = children - role_ids
        role_ids.update(frontier)
    return role_ids


def _invalidate_role_users(role_id):
    role_ids = _role_and_descendant_ids(role_id)
    user_ids = UserRole.objects.filter(role_id__in=role_ids).values_list('user_id', flat=True).distinct()
    for user_id in user_ids:
        invalidate_user_permission_cache(user_id)


@receiver(post_save, sender=UserRole, dispatch_uid='core_user_role_cache_save')
@receiver(post_delete, sender=UserRole, dispatch_uid='core_user_role_cache_delete')
def user_role_cache_changed(sender, instance, **kwargs):
    invalidate_user_permission_cache(instance.user_id)


@receiver(post_save, sender=RolePermission, dispatch_uid='core_role_permission_cache_save')
@receiver(post_delete, sender=RolePermission, dispatch_uid='core_role_permission_cache_delete')
def role_permission_cache_changed(sender, instance, **kwargs):
    _invalidate_role_users(instance.role_id)


@receiver(post_save, sender=Role, dispatch_uid='core_role_cache_save')
def role_cache_changed(sender, instance, **kwargs):
    _invalidate_role_users(instance.id)


@receiver(pre_delete, sender=Role, dispatch_uid='core_role_cache_pre_delete')
def capture_role_users_before_delete(sender, instance, **kwargs):
    role_ids = _role_and_descendant_ids(instance.id)
    instance._permission_user_ids = list(
        UserRole.objects.filter(role_id__in=role_ids).values_list('user_id', flat=True).distinct()
    )


@receiver(post_delete, sender=Role, dispatch_uid='core_role_cache_delete')
def role_cache_deleted(sender, instance, **kwargs):
    for user_id in getattr(instance, '_permission_user_ids', ()):
        invalidate_user_permission_cache(user_id)


@receiver(post_save, sender=Project, dispatch_uid='search_project_save')
@receiver(post_save, sender=Task, dispatch_uid='search_task_save')
@receiver(post_save, sender=DailyReport, dispatch_uid='search_daily_report_save')
def search_index_saved(sender, instance, **kwargs):
    schedule_sync_instance(instance)


@receiver(post_delete, sender=Project, dispatch_uid='search_project_delete')
@receiver(post_delete, sender=Task, dispatch_uid='search_task_delete')
@receiver(post_delete, sender=DailyReport, dispatch_uid='search_daily_report_delete')
def search_index_deleted(sender, instance, **kwargs):
    delete_instance(instance)


@receiver(m2m_changed, sender=DailyReport.projects.through, dispatch_uid='search_daily_report_projects')
def search_index_daily_report_projects(sender, instance, action, **kwargs):
    if action in {'post_add', 'post_remove', 'post_clear'}:
        schedule_sync_instance(instance)
