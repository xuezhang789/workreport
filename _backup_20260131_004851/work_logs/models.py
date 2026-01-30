from datetime import time
from django.db import models
from django.contrib.auth.models import User
from core.models import Profile
from projects.models import Project

class ReminderRule(models.Model):
    """日报提醒规则：按项目/角色配置提醒时间与渠道。"""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='reminder_rules', verbose_name="项目")
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True, help_text="为空则对项目内全部角色生效", verbose_name="角色")
    cutoff_time = models.TimeField(default=time(20, 0), verbose_name="截止时间")
    channel = models.CharField(max_length=50, default='email', verbose_name="通知渠道")
    weekdays_only = models.BooleanField(default=True, verbose_name="仅工作日")
    enabled = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ['project', 'role', 'cutoff_time']
        unique_together = ('project', 'role')
        verbose_name = "提醒规则"
        verbose_name_plural = "提醒规则"

    def __str__(self):
        role = self.get_role_display() if self.role else 'ALL'
        return f"{self.project.code} {role} @ {self.cutoff_time}"

class DailyReport(models.Model):
    ROLE_CHOICES = Profile.ROLE_CHOICES
    STATUS_CHOICES = [
        ('draft', '草稿 / Draft'),
        ('submitted', '已提交 / Submitted'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_reports', verbose_name="用户")
    date = models.DateField(verbose_name="日期")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, verbose_name="角色")
    project = models.CharField(max_length=200, blank=True, verbose_name="主项目(旧)")
    projects = models.ManyToManyField(Project, blank=True, related_name='reports', verbose_name="关联项目")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted', verbose_name="状态")

    # 通用字段
    today_work = models.TextField(blank=True, verbose_name="今日工作")
    progress_issues = models.TextField(blank=True, verbose_name="进度与问题")
    tomorrow_plan = models.TextField(blank=True, verbose_name="明日计划")

    # QA
    testing_scope = models.TextField(blank=True, verbose_name="测试范围")
    testing_progress = models.TextField(blank=True, verbose_name="测试进度")
    bug_summary = models.TextField(blank=True, verbose_name="缺陷汇总")
    testing_tomorrow = models.TextField(blank=True, verbose_name="明日测试计划")

    # 产品
    product_today = models.TextField(blank=True, verbose_name="今日产品工作")
    product_coordination = models.TextField(blank=True, verbose_name="协调事项")
    product_tomorrow = models.TextField(blank=True, verbose_name="明日产品计划")

    # UI
    ui_today = models.TextField(blank=True, verbose_name="今日设计工作")
    ui_feedback = models.TextField(blank=True, verbose_name="反馈修改")
    ui_tomorrow = models.TextField(blank=True, verbose_name="明日设计计划")

    # 运维
    ops_today = models.TextField(blank=True, verbose_name="今日运维工作")
    ops_monitoring = models.TextField(blank=True, verbose_name="监控状况")
    ops_tomorrow = models.TextField(blank=True, verbose_name="明日运维计划")

    # 管理
    mgr_progress = models.TextField(blank=True, verbose_name="整体进度")
    mgr_risks = models.TextField(blank=True, verbose_name="风险管理")
    mgr_tomorrow = models.TextField(blank=True, verbose_name="明日管理计划")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        unique_together = ('user', 'date', 'role')
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['role', 'date']),
            models.Index(fields=['status']),
        ]
        verbose_name = "日报"
        verbose_name_plural = "日报"

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
        return ", ".join([p.name for p in self.projects.all()])


class ReportMiss(models.Model):
    """缺报记录，便于催报与统计。"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='report_misses', verbose_name="用户")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='report_misses', verbose_name="项目")
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True, verbose_name="角色")
    date = models.DateField(verbose_name="缺报日期")
    notified_at = models.DateTimeField(null=True, blank=True, verbose_name="通知时间")
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name="补报时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录创建时间")

    class Meta:
        ordering = ['-date', '-created_at']
        unique_together = ('user', 'project', 'role', 'date')
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['user', 'date']),
        ]
        verbose_name = "缺报记录"
        verbose_name_plural = "缺报记录"

    def __str__(self):
        return f"{self.user.username} {self.date} {self.project or 'N/A'}"


class ReportTemplateVersion(models.Model):
    """日报模板版本：按角色 / 项目存储，支持共享与历史追溯。"""
    name = models.CharField(max_length=200, verbose_name="模板名称")
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True, verbose_name="适用角色")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='report_templates', verbose_name="适用项目")
    content = models.TextField(blank=True, verbose_name="模板内容")
    placeholders = models.JSONField(default=dict, blank=True, verbose_name="占位符")
    is_shared = models.BooleanField(default=True, verbose_name="是否共享")
    version = models.PositiveIntegerField(default=1, verbose_name="版本号")
    usage_count = models.PositiveIntegerField(default=0, verbose_name="使用次数")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='report_template_versions', verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['name', '-version']
        unique_together = ('name', 'project', 'role', 'version')
        verbose_name = "日报模板版本"
        verbose_name_plural = "日报模板版本"

    def __str__(self):
        target = self.project.name if self.project else 'global'
        role = dict(Profile.ROLE_CHOICES).get(self.role, self.role or 'all')
        return f"{self.name} ({target}/{role}) v{self.version}"


class RoleTemplate(models.Model):
    """日报角色模板，用于配置提示语与占位信息。"""
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, unique=True, verbose_name="角色")
    hint = models.TextField(blank=True, verbose_name="提示语")
    placeholders = models.JSONField(default=dict, blank=True, verbose_name="占位符配置")
    sample_md = models.TextField(blank=True, help_text="示例 Markdown，填写页可一键套用", verbose_name="示例内容")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    sort_order = models.IntegerField(default=0, verbose_name="排序")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['sort_order', 'role']
        verbose_name = "角色模板"
        verbose_name_plural = "角色模板"

    def __str__(self):
        return f"Template for {self.get_role_display()}"
