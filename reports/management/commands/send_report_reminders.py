from datetime import date
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q

from reports.models import DailyReport, ReminderRule, ReportMiss, Profile


class Command(BaseCommand):
    help = "扫描日报缺报并发送提醒，记录缺报列表（建议工作日 20:00 之后定时执行）。"

    def handle(self, *args, **options):
        now = timezone.localtime()
        today = date.today()
        weekday = now.weekday()  # Monday = 0

        rules = ReminderRule.objects.select_related('project').filter(enabled=True)
        total_checked = 0
        total_notified = 0
        for rule in rules:
            if rule.weekdays_only and weekday >= 5:
                continue
            # 若当前时间早于设置的截止时间，跳过（避免误发提前提醒）
            if now.time() < rule.cutoff_time:
                continue

            project = rule.project
            users = self._project_users(project, role=rule.role)

            for user in users:
                total_checked += 1
                # 已提交则跳过
                if DailyReport.objects.filter(user=user, date=today, status='submitted').exists():
                    continue

                # 生成缺报记录
                user_role = None
                try:
                    user_role = user.profile.position
                except Exception:
                    user_role = rule.role

                miss, created = ReportMiss.objects.get_or_create(
                    user=user,
                    project=project,
                    role=user_role,
                    date=today,
                    defaults={'notified_at': now},
                )
                should_notify = created or miss.notified_at is None
                if miss.notified_at is None:
                    miss.notified_at = now
                    miss.save(update_fields=['notified_at'])

                if user.email and should_notify:
                    self._send_email(user, project.name, today)
                    total_notified += 1

        self.stdout.write(self.style.SUCCESS(f"检查用户 {total_checked} 个，发送提醒 {total_notified} 封。"))

    def _project_users(self, project, role=None):
        User = get_user_model()
        base_q = Q(project_memberships=project) | Q(managed_projects=project) | Q(owned_projects=project)
        qs = User.objects.filter(base_q).distinct()
        if role:
            qs = qs.filter(profile__position=role)
        return qs

    def _send_email(self, user, project_name, target_date):
        subject = f"[提醒] 您尚未提交 {target_date} 的日报 - {project_name}"
        name = user.get_full_name() or user.username
        body = (
            f"{name}，您好：\n\n"
            f"检测到您尚未提交 {target_date} 的日报（项目：{project_name}）。\n"
            "请于收到邮件后尽快补交，感谢配合。\n"
        )
        send_mail(subject, body, None, [user.email], fail_silently=True)
