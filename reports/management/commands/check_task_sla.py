from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail

from reports.models import Task, TaskSlaTimer, TaskHistory
from reports.views import get_sla_thresholds


class Command(BaseCommand):
    help = "扫描任务 SLA/截止时间，自动标记逾期并发送提醒；更新暂停计时。"

    def handle(self, *args, **options):
        now = timezone.now()
        tasks = Task.objects.select_related('project', 'user', 'sla_timer').filter(
            status__in=['pending', 'in_progress', 'on_hold', 'reopened']
        )
        overdue_count = 0
        notified_count = 0

        thresholds = get_sla_thresholds()
        amber_limit = thresholds.get('amber', 6)
        red_limit = thresholds.get('red', 2)

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
            remaining_hours = None
            sla_deadline = None
            if task.due_at and task.due_at < now:
                is_overdue = True
                deadline_display = task.due_at
            elif task.project.sla_hours:
                sla_deadline = task.created_at + timedelta(hours=task.project.sla_hours, seconds=paused_seconds)
                remaining_hours = round((sla_deadline - now).total_seconds() / 3600, 1)
                if now > sla_deadline:
                    is_overdue = True
                    deadline_display = sla_deadline
                else:
                    deadline_display = sla_deadline
            elif task.due_at:
                remaining_hours = round((task.due_at - now).total_seconds() / 3600, 1)
                deadline_display = task.due_at

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

            # SLA 升级提醒（未逾期且仅提醒一次）
            if not is_overdue and remaining_hours is not None:
                if remaining_hours <= red_limit and not task.red_notified_at:
                    self._notify_sla(task, 'red', deadline_display)
                    task.red_notified_at = now
                    task.save(update_fields=['red_notified_at'])
                    notified_count += 1
                elif remaining_hours <= amber_limit and not task.amber_notified_at:
                    self._notify_sla(task, 'amber', deadline_display)
                    task.amber_notified_at = now
                    task.save(update_fields=['amber_notified_at'])
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

    def _notify_sla(self, task, level, deadline):
        if not task.user.email:
            return
        label = "SLA 红色提醒" if level == 'red' else "SLA 黄色提醒"
        subject = f"[{label}] {task.title}"
        deadline_text = timezone.localtime(deadline).strftime("%Y-%m-%d %H:%M") if deadline else "未提供"
        body = (
            f"{task.user.get_full_name() or task.user.username}，您好：\n\n"
            f"任务《{task.title}》即将超出 SLA，当前等级：{label}。\n"
            f"项目：{task.project.name}\n"
            f"SLA 截止：{deadline_text}\n"
            "请尽快处理或与管理员沟通调整。\n"
        )
        send_mail(subject, body, None, [task.user.email], fail_silently=True)
