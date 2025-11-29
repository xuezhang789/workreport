from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.utils import timezone

from reports.models import Task, TaskSlaTimer, TaskHistory


class Command(BaseCommand):
    help = "扫描任务 SLA/截止时间，自动标记逾期并发送提醒；更新暂停计时。"

    def handle(self, *args, **options):
        now = timezone.now()
        tasks = Task.objects.select_related('project', 'user', 'sla_timer').filter(
            status__in=['pending', 'in_progress', 'on_hold', 'reopened']
        )
        overdue_count = 0
        notified_count = 0

        for task in tasks:
            timer = task.sla_timer if hasattr(task, 'sla_timer') else None
            if timer is None:
                timer = TaskSlaTimer.objects.create(task=task)

            paused_seconds = timer.total_paused_seconds
            if task.status == 'on_hold' and timer.paused_at:
                paused_seconds += int((now - timer.paused_at).total_seconds())

            # 判定逾期：1) 明确截止时间；2) 项目 SLA 小时
            is_overdue = False
            deadline_display = None
            if task.due_at and task.due_at < now:
                is_overdue = True
                deadline_display = task.due_at
            elif task.project.sla_hours:
                sla_deadline = task.created_at + timedelta(hours=task.project.sla_hours, seconds=paused_seconds)
                if now > sla_deadline:
                    is_overdue = True
                    deadline_display = sla_deadline

            if is_overdue and task.status != 'overdue':
                old_status = task.status
                task.status = 'overdue'
                task.save(update_fields=['status'])
                TaskHistory.objects.create(
                    task=task,
                    user=None,
                    field='status',
                    old_value=old_status,
                    new_value='overdue',
                )
                overdue_count += 1

            if is_overdue and not task.overdue_notified_at:
                self._notify_overdue(task, deadline_display)
                task.overdue_notified_at = now
                task.save(update_fields=['overdue_notified_at'])
                notified_count += 1

        self.stdout.write(self.style.SUCCESS(f"逾期标记 {overdue_count} 条，发送提醒 {notified_count} 条。"))

    def _notify_overdue(self, task, deadline):
        if not task.user.email:
            return
        subject = f"[任务逾期] {task.title}"
        deadline_text = timezone.localtime(deadline).strftime("%Y-%m-%d %H:%M") if deadline else "未提供"
        body = (
            f"{task.user.get_full_name() or task.user.username}，您好：\n\n"
            f"任务《{task.title}》已逾期。\n"
            f"项目：{task.project.name}\n"
            f"截止：{deadline_text}\n"
            "请尽快处理或与管理员沟通调整。\n"
        )
        send_mail(subject, body, None, [task.user.email], fail_silently=True)
