from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.core.cache import cache
from reports.models import Project, Task, DailyReport, AuditLog
from reports.middleware import get_current_user, get_current_ip
from reports.services.audit_service import AuditService

TRACKED_MODELS = [Project, Task, DailyReport, User]

def _invalidate_stats_cache(sender=None, **kwargs):
    """
    Invalidate statistics cache. Can be used as a signal receiver or helper.
    """
    try:
        cache.delete_pattern("stats_*")
    except Exception:
        pass

@receiver(pre_save)
def audit_pre_save(sender, instance, **kwargs):
    if sender not in TRACKED_MODELS:
        return
    
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            instance._audit_diff = AuditService._calculate_diff(old_instance, instance)
        except sender.DoesNotExist:
            instance._audit_diff = None
    else:
        instance._audit_diff = None

@receiver(post_save)
def audit_post_save(sender, instance, created, **kwargs):
    # Cache Invalidation for core models
    if sender in [Project, Task, DailyReport]:
        _invalidate_stats_cache()

    if sender not in TRACKED_MODELS:
        return

    user = get_current_user()
    ip = get_current_ip()
    
    if created:
        AuditService.log_change(user, 'create', instance, ip=ip)
    else:
        # Update
        if hasattr(instance, '_audit_diff') and instance._audit_diff:
            AuditService.log_change(
                user, 
                'update', 
                instance, 
                ip=ip, 
                changes=instance._audit_diff
            )

@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    if sender in [Project, Task, DailyReport]:
        _invalidate_stats_cache()

    if sender not in TRACKED_MODELS:
        return

    user = get_current_user()
    ip = get_current_ip()
    
    AuditService.log_change(user, 'delete', instance, ip=ip)
