from django.db.models.signals import pre_save, post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from projects.models import Project, ProjectPhaseConfig, ProjectPhaseChangeLog
from tasks.models import Task, TaskComment
from work_logs.models import DailyReport
from audit.models import AuditLog
from core.models import UserRole
from reports.middleware import get_current_user, get_current_ip
from reports.services.audit_service import AuditService
from reports.services.notification_service import send_notification
from core.services.notification_template import NotificationContent, NotificationItem, NotificationAction

TRACKED_MODELS = [DailyReport, User]

def _invalidate_stats_cache(sender=None, **kwargs):
    """
    使统计缓存无效。可以用作信号接收器或助手。
    """
    try:
        # 尝试使用模式删除（例如 django-redis）
        cache.delete_pattern("stats_*")
    except (AttributeError, Exception):
        # 对于不支持 delete_pattern 的后端的回退（例如测试中的 LocMemCache）
        cache.clear()

@receiver(pre_save)
def audit_pre_save(sender, instance, **kwargs):
    if sender not in TRACKED_MODELS:
        return
    
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            instance._audit_diff = AuditService._calculate_diff(old_instance, instance)
            instance._old_instance = old_instance # 保留 post_save 逻辑的引用
        except sender.DoesNotExist:
            instance._audit_diff = None
    else:
        instance._audit_diff = None

@receiver(post_save)
def audit_post_save(sender, instance, created, **kwargs):
    # 核心模型的缓存失效
    if sender in [Project, Task, DailyReport]:
        _invalidate_stats_cache()

    if sender not in TRACKED_MODELS:
        return

    user = get_current_user()
    ip = get_current_ip()
    
    if created:
        try:
            AuditService.log_change(user, 'create', instance, ip=ip)
        except Exception as e:
            # 当 AuditLog 表不存在时的回退（例如在初始迁移/创建期间）
            # 这对于“createsuperuser”在全新数据库上工作至关重要
            print(f"Warning: Failed to log audit creation (likely table missing): {e}")
    else:
        # Update
        if hasattr(instance, '_audit_diff') and instance._audit_diff:
            try:
                AuditService.log_change(
                    user, 
                    'update', 
                    instance, 
                    ip=ip, 
                    changes=instance._audit_diff
                )
            except Exception as e:
                print(f"Warning: Failed to log audit update: {e}")

@receiver(post_delete)
def audit_post_delete(sender, instance, **kwargs):
    if sender in [Project, Task, DailyReport]:
        _invalidate_stats_cache()

    if sender not in TRACKED_MODELS:
        return

    user = get_current_user()
    ip = get_current_ip()
    
    try:
        AuditService.log_change(user, 'delete', instance, ip=ip)
    except Exception as e:
        print(f"Warning: Failed to log audit delete: {e}")

@receiver(post_save, sender=Task)
def notify_task_assignment(sender, instance, created, **kwargs):
    """
    当任务分配给用户或状态/优先级更改时通知用户。
    """
    current_operator = get_current_user()

    if created:
        # 分配了新任务
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
        # 更新场景
        if hasattr(instance, '_audit_diff') and instance._audit_diff:
            diff = instance._audit_diff
            
            # 1. 用户重新分配
            if 'user' in diff:
                new_user_username = diff['user']['new']
                # 通知新用户
                if instance.user and instance.user != current_operator:
                    send_notification(
                        user=instance.user,
                        title="任务转交 / Task Assigned",
                        message=f"任务 {instance.title} 已转交给您",
                        notification_type='task_assigned',
                        priority='high',
                        data={'task_id': instance.id, 'project_id': instance.project_id}
                    )
            
            # 2. 状态变更
            if 'status' in diff:
                old_status = diff['status']['old']
                new_status = diff['status']['new']
                
                # 通知所有者（如果不是操作员）
                if instance.user and instance.user != current_operator:
                    send_notification(
                        user=instance.user,
                        title="任务状态更新 / Task Status Updated",
                        message=f"任务 {instance.title} 状态从 {old_status} 变更为 {new_status}",
                        notification_type='task_updated',
                        priority='normal',
                        data={'task_id': instance.id, 'project_id': instance.project_id, 'diff': diff}
                    )
                
                # 通知协作者
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

            # 3. 优先级变更（高优先级警报）
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
    当项目阶段变更或发生关键更新时通知成员。
    """
    if created:
        return
        
    current_operator = get_current_user()
    
    if hasattr(instance, '_audit_diff') and instance._audit_diff:
        diff = instance._audit_diff
        
        # 跟踪阶段和进度字段
        monitored_fields = ['current_phase', 'overall_progress', 'start_date', 'end_date', 'progress_note']
        if not any(field in diff for field in monitored_fields):
            return

        # 准备日志数据
        old_phase = None
        new_phase = None
        old_progress = 0
        new_progress = 0
        
        # 处理阶段
        if 'current_phase' in diff:
            new_phase = instance.current_phase
            if hasattr(instance, '_old_instance'):
                old_phase = instance._old_instance.current_phase
        else:
            new_phase = instance.current_phase
            old_phase = instance.current_phase

        # 处理进度
        if 'overall_progress' in diff:
            old_progress = diff['overall_progress']['old'] or 0
            new_progress = diff['overall_progress']['new'] or 0
        else:
            new_progress = instance.overall_progress
            old_progress = instance.overall_progress # 假设没有变化

        # 创建变更日志
        details = {}
        for field in monitored_fields:
            if field in diff:
                # 存储日期/备注的字符串表示形式
                details[field] = {
                    'old': str(diff[field]['old']) if diff[field]['old'] is not None else None,
                    'new': str(diff[field]['new']) if diff[field]['new'] is not None else None
                }

        ProjectPhaseChangeLog.objects.create(
            project=instance,
            old_phase=old_phase,
            new_phase=new_phase,
            old_progress=old_progress,
            new_progress=new_progress,
            details=details,
            changed_by=current_operator
        )

        # 确定收件人
        recipients = set()
        
        # 1. 项目经理（所有者 + 经理）
        if instance.owner:
            recipients.add(instance.owner)
        recipients.update(instance.managers.all())
        
        # 2. 阶段负责人（动态角色）
        if new_phase and new_phase.related_role:
            # 在此项目范围内查找具有此角色的用户
            scope = f"project:{instance.id}"
            role_users = UserRole.objects.filter(
                role=new_phase.related_role,
                scope__in=[scope, None] # 项目范围或全局
            ).values_list('user_id', flat=True)
            
            if role_users:
                recipients.update(User.objects.filter(id__in=role_users))

        # 从收件人中移除操作员
        if current_operator in recipients:
            recipients.remove(current_operator)
            
        if not recipients:
            return

        # 构建统一通知内容
        content = NotificationContent(
            title=f"项目进度更新 / Project Progress Updated",
            subtitle=instance.name,
            body=f"项目 {instance.name} 发生重要变更，请查阅以下详情。",
            actions=[
                NotificationAction(label="查看详情 / View Details", url=f"/projects/{instance.id}/")
            ],
            meta={
                'project_id': instance.id,
                'diff': details,
                'timestamp': timezone.now().isoformat()
            }
        )

        if 'current_phase' in diff:
            p_name = new_phase.phase_name if new_phase else "None"
            old_p_name = old_phase.phase_name if old_phase else "None"
            content.items.append(NotificationItem(
                label="阶段 / Phase",
                value=p_name,
                old_value=old_p_name,
                highlight=True
            ))
            
        if 'overall_progress' in diff:
            content.items.append(NotificationItem(
                label="进度 / Progress",
                value=f"{new_progress}%",
                old_value=f"{old_progress}%",
                highlight=True
            ))
            
        if 'start_date' in diff:
            content.items.append(NotificationItem(
                label="开始日期 / Start Date",
                value=str(diff['start_date']['new']),
                old_value=str(diff['start_date']['old'])
            ))
            
        if 'end_date' in diff:
            content.items.append(NotificationItem(
                label="结束日期 / End Date",
                value=str(diff['end_date']['new']),
                old_value=str(diff['end_date']['old'])
            ))
            
        if 'progress_note' in diff:
             content.items.append(NotificationItem(
                label="备注 / Note",
                value="已更新 / Updated",
                old_value=None
            ))

        # 发送通知
        for user in recipients:
            send_notification(
                user=user,
                title=f"{content.title}: {instance.name}",
                message=content.body,
                notification_type='project_update',
                priority='high',
                data={'project_id': instance.id, 'diff': details},
                content=content
            )
@receiver(post_save, sender=TaskComment)
def notify_comment_mention(sender, instance, created, **kwargs):
    """
    通知评论中提到的用户。
    """
    if not created:
        return
        
    mentions = instance.mentions # 用户名或 ID 列表？模型显示为 JSONField。
    # 假设 mentions 是基于典型实现的用户名列表
    if not mentions:
        return
        
    for username in mentions:
        try:
            user = User.objects.get(username=username)
            if user == instance.user:
                continue # 不通知自己
                
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
            
    # 如果其他人评论，也通知任务所有者
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
    # 处理 DailyReport.projects 变更
    if isinstance(instance, DailyReport) and action in ["post_add", "post_remove", "post_clear"]:
        _invalidate_stats_cache()
