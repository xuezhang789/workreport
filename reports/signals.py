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
    Notify user when a task is assigned to them or status/priority changes.
    """
    current_operator = get_current_user()

    if created:
        # New task assigned
        if instance.user and instance.user != current_operator:
            send_notification(
                user=instance.user,
                title="新任务分配 / New Task Assigned",
                message=f"您被分配了新任务：{instance.title}",
                notification_type='task_assigned',
                priority='high',
                data={'task_id': instance.id, 'project_id': instance.project_id}
            )
    else:
        # Update Scenarios
        if hasattr(instance, '_audit_diff') and instance._audit_diff:
            diff = instance._audit_diff
            
            # 1. User Re-assignment
            if 'user' in diff:
                new_user_username = diff['user']['new']
                # Notify new user
                if instance.user and instance.user != current_operator:
                    send_notification(
                        user=instance.user,
                        title="任务转交 / Task Assigned",
                        message=f"任务 {instance.title} 已转交给您",
                        notification_type='task_assigned',
                        priority='high',
                        data={'task_id': instance.id, 'project_id': instance.project_id}
                    )
            
            # 2. Status Change
            if 'status' in diff:
                old_status = diff['status']['old']
                new_status = diff['status']['new']
                
                # Notify Owner (if not operator)
                if instance.user and instance.user != current_operator:
                    send_notification(
                        user=instance.user,
                        title="任务状态更新 / Task Status Updated",
                        message=f"任务 {instance.title} 状态从 {old_status} 变更为 {new_status}",
                        notification_type='task_updated',
                        priority='normal',
                        data={'task_id': instance.id, 'project_id': instance.project_id, 'diff': diff}
                    )
                
                # Notify Collaborators
                for collaborator in instance.collaborators.all():
                    if collaborator != current_operator and collaborator != instance.user:
                        send_notification(
                            user=collaborator,
                            title="协作任务更新 / Collaborated Task Updated",
                            message=f"您协作的任务 {instance.title} 状态更新为 {new_status}",
                            notification_type='task_updated',
                            priority='normal',
                            data={'task_id': instance.id, 'project_id': instance.project_id}
                        )

            # 3. Priority Change (High Priority Alert)
            if 'priority' in diff:
                new_priority = diff['priority']['new']
                if new_priority == 'high' and instance.user != current_operator:
                     send_notification(
                        user=instance.user,
                        title="任务优先级升级 / Task Priority Escalated",
                        message=f"任务 {instance.title} 优先级调整为 高 (High)",
                        notification_type='task_updated',
                        priority='high',
                        data={'task_id': instance.id, 'project_id': instance.project_id}
                    )

@receiver(post_save, sender=Project)
def notify_project_change(sender, instance, created, **kwargs):
    """
    Notify members when project phase changes or critical updates occur.
    """
    if created:
        return
        
    current_operator = get_current_user()
    
    if hasattr(instance, '_audit_diff') and instance._audit_diff:
        diff = instance._audit_diff
        
        # Phase Change Notification
        if 'phase' in diff:
            new_phase = diff['phase']['new']
            # Notify all managers and members
            recipients = set(instance.managers.all()) | set(instance.members.all())
            if instance.owner:
                recipients.add(instance.owner)
                
            for user in recipients:
                if user != current_operator:
                    phase_name = instance.current_phase.phase_name if instance.current_phase else "Unknown"
                    send_notification(
                        user=user,
                        title="项目阶段变更 / Project Phase Changed",
                        message=f"项目 {instance.name} 进入新阶段：{phase_name}",
                        notification_type='project_update',
                        priority='high',
                        data={'project_id': instance.id, 'phase': new_phase}
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
                title="评论提及 / Mentioned in Comment",
                message=f"{instance.user.username} 在任务 {instance.task.title} 的评论中提到了您",
                notification_type='task_mention',
                priority='high',
                data={'task_id': instance.task.id, 'comment_id': instance.id}
            )
        except User.DoesNotExist:
            pass
            
    # Also notify task owner if someone else comments
    task_owner = instance.task.user
    if task_owner != instance.user and (not mentions or task_owner.username not in mentions):
        send_notification(
            user=task_owner,
            title="新评论 / New Comment",
            message=f"{instance.user.username} 评论了您的任务 {instance.task.title}",
            notification_type='task_updated',
            priority='normal',
            data={'task_id': instance.task.id, 'comment_id': instance.id}
        )

@receiver(m2m_changed)
def audit_m2m_changed(sender, instance, action, **kwargs):
    # Handle DailyReport.projects changes
    if isinstance(instance, DailyReport) and action in ["post_add", "post_remove", "post_clear"]:
        _invalidate_stats_cache()
