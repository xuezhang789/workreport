from datetime import time
from django.db import models
from django.contrib.auth.models import User


class Profile(models.Model):
    ROLE_CHOICES = [
        ('dev', '开发 / Developer'),
        ('qa', '测试 / QA'),
        ('pm', '产品 / Product Manager'),
        ('ui', '设计 / UI / UX'),
        ('ops', '运维 / Ops'),
        ('mgr', '项目管理 / PM / PMO'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    position = models.CharField(max_length=10, choices=ROLE_CHOICES, default='dev')

    def __str__(self):
        return f"{self.user.username} - {self.get_position_display()}"


class Project(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_projects')
    members = models.ManyToManyField(User, blank=True, related_name='project_memberships')
    managers = models.ManyToManyField(User, blank=True, related_name='managed_projects')
    is_active = models.BooleanField(default=True)
    sla_hours = models.PositiveIntegerField(null=True, blank=True, help_text="项目级 SLA 提醒窗口（小时）")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.code} - {self.name}"


class ReminderRule(models.Model):
    """日报提醒规则：按项目/角色配置提醒时间与渠道。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='reminder_rules')
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True, help_text="为空则对项目内全部角色生效")
    cutoff_time = models.TimeField(default=time(20, 0))
    channel = models.CharField(max_length=50, default='email')
    weekdays_only = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['project', 'role', 'cutoff_time']
        unique_together = ('project', 'role')

    def __str__(self):
        role = self.get_role_display() if self.role else 'ALL'
        return f"{self.project.code} {role} @ {self.cutoff_time}"


class ReportMiss(models.Model):
    """缺报记录，便于催报与统计。"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='report_misses')
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='report_misses')
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True)
    date = models.DateField()
    notified_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']
        unique_together = ('user', 'project', 'role', 'date')
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['user', 'date']),
        ]

    def __str__(self):
        return f"{self.user.username} {self.date} {self.project or 'N/A'}"


class DailyReport(models.Model):
    ROLE_CHOICES = Profile.ROLE_CHOICES
    STATUS_CHOICES = [
        ('draft', '草稿 / Draft'),
        ('submitted', '已提交 / Submitted'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_reports')
    date = models.DateField()
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    project = models.CharField(max_length=200, blank=True)
    projects = models.ManyToManyField(Project, blank=True, related_name='reports')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')

    # 通用字段
    today_work = models.TextField(blank=True)
    progress_issues = models.TextField(blank=True)
    tomorrow_plan = models.TextField(blank=True)

    # QA
    testing_scope = models.TextField(blank=True)
    testing_progress = models.TextField(blank=True)
    bug_summary = models.TextField(blank=True)
    testing_tomorrow = models.TextField(blank=True)

    # 产品
    product_today = models.TextField(blank=True)
    product_coordination = models.TextField(blank=True)
    product_tomorrow = models.TextField(blank=True)

    # UI
    ui_today = models.TextField(blank=True)
    ui_feedback = models.TextField(blank=True)
    ui_tomorrow = models.TextField(blank=True)

    # 运维
    ops_today = models.TextField(blank=True)
    ops_monitoring = models.TextField(blank=True)
    ops_tomorrow = models.TextField(blank=True)

    # 管理
    mgr_progress = models.TextField(blank=True)
    mgr_risks = models.TextField(blank=True)
    mgr_tomorrow = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'date', 'role')
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['role', 'date']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.get_role_display()}"

    @property
    def summary(self):
        """
        Return the first non-empty summary-like field for display/export.
        """
        for field in [
            'today_work',
            'testing_scope',
            'product_today',
            'ui_today',
            'ops_today',
            'mgr_progress',
        ]:
            value = getattr(self, field, '')
            if value:
                return value
        return ''

    @property
    def project_names(self):
        return ", ".join(self.projects.values_list('name', flat=True)) if self.projects.exists() else ''


class RoleTemplate(models.Model):
    """日报角色模板，用于配置提示语与占位信息。"""
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, unique=True)
    hint = models.TextField(blank=True)
    placeholders = models.JSONField(default=dict, blank=True)
    sample_md = models.TextField(blank=True, help_text="示例 Markdown，填写页可一键套用")
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'role']

    def __str__(self):
        return f"Template for {self.get_role_display()}"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('export', '导出'),
        ('delete', '删除'),
        ('create', '创建'),
        ('update', '更新'),
        ('access', '访问'),
    ]
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    ip = models.GenericIPAddressField(null=True, blank=True)
    extra = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        who = self.user.username if self.user else 'anonymous'
        return f"{self.action} by {who} at {self.created_at:%Y-%m-%d %H:%M:%S}"


class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', '未开始 / Pending'),
        ('in_progress', '进行中 / In Progress'),
        ('on_hold', '挂起 / On Hold'),
        ('completed', '已完成 / Completed'),
        ('overdue', '逾期 / Overdue'),
        ('reopened', '重新打开 / Reopened'),
    ]

    title = models.CharField(max_length=200)
    url = models.URLField(blank=True)
    content = models.TextField(blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks')
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    overdue_notified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['project', 'status']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['due_at']),
        ]

    def __str__(self):
        return f"{self.title} -> {self.user.username}"


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_comments')
    content = models.TextField()
    mentions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Comment by {self.user.username} on {self.task_id}"


class TaskAttachment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='attachments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_attachments')
    url = models.URLField(blank=True)
    file = models.FileField(upload_to='task_attachments/', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Attachment for {self.task_id}"


class TaskSlaTimer(models.Model):
    """任务 SLA 计时：支持暂停/恢复并记录累计暂停时长。"""
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name='sla_timer')
    paused_at = models.DateTimeField(null=True, blank=True)
    total_paused_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"SLA timer for task {self.task_id}"


class SystemSetting(models.Model):
    """简单的键值配置存储，支持 SLA 等后台可调参数。"""
    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key']

    def __str__(self):
        return f"{self.key}={self.value}"


class TaskHistory(models.Model):
    """任务变更历史：状态、截止时间、指派人等变更记录。"""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='histories')
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='task_histories')
    field = models.CharField(max_length=50)
    old_value = models.CharField(max_length=200, blank=True)
    new_value = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.task_id} {self.field}: {self.old_value} -> {self.new_value}"
