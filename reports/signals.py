from django.db.models.signals import pre_save, post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.core.cache import cache
from reports.models import Project, Task, DailyReport, AuditLog, TaskComment
from reports.middleware import get_current_user, get_current_ip
from reports.services.audit_service import AuditService
from reports.services.notification_service import send_notification

TRACKED_MODELS = [DailyReport, User]

def _invalidate_stats_cache(sender=None, **kwargs):
    """
    Invalidate statistics cache. Can be used as a signal receiver or helper.
    """
    try:
        # Attempt to use pattern deletion (e.g., django-redis)
        cache.delete_pattern("stats_*")
    except (AttributeError, Exception):
        # Fallback for backends without delete_pattern (e.g., LocMemCache in tests)
        cache.clear()

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

@receiver(post_save, sender=Task)
def notify_task_assignment(sender, instance, created, **kwargs):
    """
    Notify user when a task is assigned to them.
    """
    if created:
        # New task assigned
        send_notification(
            user=instance.user,
            title="新任务分配",
            message=f"您被分配了新任务：{instance.title}",
            notification_type='task_assigned',
            data={'task_id': instance.id, 'project_id': instance.project_id}
        )
    else:
        # Check if user changed
        if hasattr(instance, '_audit_diff') and instance._audit_diff and 'user' in instance._audit_diff:
            # User changed
            new_user_username = instance._audit_diff['user']['new']
            # We need the User object, not just username.
            # But wait, instance.user IS the new user object (unless it's just an ID change logic, but ORM instance.user is the object)
            # So we can just use instance.user.
            
            # Only notify if the new user is different from the current operator (optional, but good UX)
            current_operator = get_current_user()
            if current_operator and current_operator == instance.user:
                pass # Don't notify if I assigned it to myself
            else:
                send_notification(
                    user=instance.user,
                    title="任务转交",
                    message=f"任务 {instance.title} 已转交给您",
                    notification_type='task_assigned',
                    data={'task_id': instance.id, 'project_id': instance.project_id}
                )

@receiver(post_save, sender=TaskComment)
def notify_comment_mention(sender, instance, created, **kwargs):
    """
    Notify users mentioned in a comment.
    """
    if not created:
        return
        
    mentions = instance.mentions # List of usernames or IDs? Model says JSONField.
    # Assuming mentions is a list of usernames for now based on typical implementation
    if not mentions:
        return
        
    for username in mentions:
        try:
            user = User.objects.get(username=username)
            if user == instance.user:
                continue # Don't notify self
                
            send_notification(
                user=user,
                title="评论提及",
                message=f"{instance.user.username} 在任务 {instance.task.title} 的评论中提到了您",
                notification_type='task_mention',
                data={'task_id': instance.task.id, 'comment_id': instance.id}
            )
        except User.DoesNotExist:
            pass
            
    # Also notify task owner if someone else comments
    task_owner = instance.task.user
    if task_owner != instance.user and (not mentions or task_owner.username not in mentions):
        send_notification(
            user=task_owner,
            title="新评论",
            message=f"{instance.user.username} 评论了您的任务 {instance.task.title}",
            notification_type='task_updated',
            data={'task_id': instance.task.id, 'comment_id': instance.id}
        )

@receiver(m2m_changed)
def audit_m2m_changed(sender, instance, action, **kwargs):
    # Handle DailyReport.projects changes
    if isinstance(instance, DailyReport) and action in ["post_add", "post_remove", "post_clear"]:
        _invalidate_stats_cache()
