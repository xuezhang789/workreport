from datetime import time, timedelta
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Profile(models.Model):
    ROLE_CHOICES = [
        ('dev', '开发 / Developer'),
        ('qa', '测试 / QA'),
        ('pm', '产品 / Product Manager'),
        ('ui', '设计 / UI / UX'),
        ('ops', '运维 / Ops'),
        ('mgr', '项目管理 / PM / PMO'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name="用户")
    position = models.CharField(max_length=10, choices=ROLE_CHOICES, default='dev', verbose_name="职位")

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    def __str__(self):
        return f"{self.user.username} - {self.get_position_display()}"


class ProjectPhaseConfig(models.Model):
    phase_name = models.CharField(max_length=50, verbose_name="阶段名称")
    progress_percentage = models.PositiveIntegerField(help_text="0-100", verbose_name="进度百分比")
    order_index = models.PositiveIntegerField(default=0, verbose_name="排序索引")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    class Meta:
        ordering = ['order_index']
        verbose_name = "项目阶段配置"
        verbose_name_plural = "项目阶段配置"

    def __str__(self):
        return f"{self.phase_name} ({self.progress_percentage}%)"


class Project(models.Model):
    name = models.CharField(max_length=200, verbose_name="项目名称")
    code = models.CharField(max_length=50, unique=True, verbose_name="项目代号")
    description = models.TextField(blank=True, verbose_name="项目描述")
    start_date = models.DateField(null=True, blank=True, verbose_name="开始日期")
    end_date = models.DateField(null=True, blank=True, verbose_name="结束日期")
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_projects', verbose_name="负责人")
    members = models.ManyToManyField(User, blank=True, related_name='project_memberships', verbose_name="项目成员")
    managers = models.ManyToManyField(User, blank=True, related_name='managed_projects', verbose_name="项目经理")
    is_active = models.BooleanField(default=True, verbose_name="是否激活")
    sla_hours = models.PositiveIntegerField(null=True, blank=True, help_text="项目级 SLA 提醒窗口（小时）", verbose_name="SLA时限(小时)")
    
    # New fields for Phase Management
    current_phase = models.ForeignKey(ProjectPhaseConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects', verbose_name="当前阶段")
    overall_progress = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="总体进度(%)")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['name']
        verbose_name = "项目"
        verbose_name_plural = "项目"
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProjectPhaseChangeLog(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='phase_logs', verbose_name="项目")
    old_phase = models.ForeignKey(ProjectPhaseConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='log_as_old', verbose_name="原阶段")
    new_phase = models.ForeignKey(ProjectPhaseConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name='log_as_new', verbose_name="新阶段")
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="变更人")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="变更时间")

    class Meta:
        ordering = ['-changed_at']
        verbose_name = "项目阶段变更日志"
        verbose_name_plural = "项目阶段变更日志"

    def __str__(self):
        return f"{self.project.name}: {self.old_phase} -> {self.new_phase}"

class ProjectAttachment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='attachments', verbose_name="项目")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uploaded_project_attachments', verbose_name="上传人")
    file = models.FileField(upload_to='project_attachments/', verbose_name="文件")
    original_filename = models.CharField(max_length=255, verbose_name="原始文件名")
    file_size = models.PositiveIntegerField(default=0, verbose_name="文件大小(Bytes)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "项目附件"
        verbose_name_plural = "项目附件"

    def __str__(self):
        return f"{self.original_filename} ({self.project.name})"

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


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('export', '导出'),
        ('delete', '删除'),
        ('create', '创建'),
        ('update', '更新'),
        ('access', '访问'),
        ('other', '其他'),
    ]
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs', verbose_name="用户")
    operator_name = models.CharField(max_length=150, blank=True, verbose_name="操作人姓名")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="动作")
    path = models.CharField(max_length=255, verbose_name="路径", blank=True)
    method = models.CharField(max_length=10, verbose_name="方法", blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP地址")
    
    # Core Entity Info
    entity_type = models.CharField(max_length=100, blank=True, verbose_name="实体类型")
    entity_id = models.CharField(max_length=100, blank=True, verbose_name="实体ID")
    
    # Detailed Changes
    changes = models.JSONField(default=dict, blank=True, verbose_name="变更详情")
    
    # Project Context
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs', verbose_name="关联项目")
    
    # Task Context
    task = models.ForeignKey('Task', null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs', verbose_name="关联任务")

    extra = models.TextField(blank=True, verbose_name="额外信息")
    remarks = models.TextField(blank=True, verbose_name="备注")
    data = models.JSONField(default=dict, blank=True, verbose_name="数据快照")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
            models.Index(fields=['project']),
            models.Index(fields=['task']),
        ]

    def __str__(self):
        who = self.operator_name or (self.user.username if self.user else 'anonymous')
        return f"{self.action} {self.entity_type}#{self.entity_id} by {who} at {self.created_at:%Y-%m-%d %H:%M:%S}"


class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', '未开始 / Pending'),
        ('in_progress', '进行中 / In Progress'),
        ('on_hold', '挂起 / On Hold'),
        ('completed', '已完成 / Completed'),
        ('overdue', '逾期 / Overdue'),
        ('reopened', '重新打开 / Reopened'),
    ]

    PRIORITY_CHOICES = [
        ('high', '高 / High'),
        ('medium', '中 / Medium'),
        ('low', '低 / Low'),
    ]

    title = models.CharField(max_length=200, verbose_name="标题")
    url = models.URLField(blank=True, verbose_name="链接")
    content = models.TextField(blank=True, verbose_name="内容")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tasks', verbose_name="主负责人")
    collaborators = models.ManyToManyField(User, related_name='collaborated_tasks', blank=True, verbose_name="协作人")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks', verbose_name="项目")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium', verbose_name="优先级")
    due_at = models.DateTimeField(null=True, blank=True, verbose_name="截止时间")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成时间")
    overdue_notified_at = models.DateTimeField(null=True, blank=True, verbose_name="逾期通知时间")
    amber_notified_at = models.DateTimeField(null=True, blank=True, verbose_name="即将逾期通知时间")
    red_notified_at = models.DateTimeField(null=True, blank=True, verbose_name="紧急通知时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['project', 'status']),
            models.Index(fields=['user', 'status']),
            models.Index(fields=['project']),
            models.Index(fields=['user']),
            models.Index(fields=['created_at']),
            models.Index(fields=['due_at']),
        ]
        verbose_name = "任务"
        verbose_name_plural = "任务"

    def __str__(self):
        return f"{self.title} -> {self.user.username}"


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments', verbose_name="任务")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_comments', verbose_name="用户")
    content = models.TextField(verbose_name="评论内容")
    mentions = models.JSONField(default=list, blank=True, verbose_name="提及用户")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="评论时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "任务评论"
        verbose_name_plural = "任务评论"

    def __str__(self):
        return f"Comment by {self.user.username} on {self.task_id}"


class TaskAttachment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='attachments', verbose_name="任务")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='task_attachments', verbose_name="用户")
    url = models.URLField(blank=True, verbose_name="链接")
    file = models.FileField(upload_to='task_attachments/', null=True, blank=True, verbose_name="文件")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "任务附件"
        verbose_name_plural = "任务附件"

    def __str__(self):
        return f"Attachment for {self.task_id}"


class TaskSlaTimer(models.Model):
    """任务 SLA 计时：支持暂停/恢复并记录累计暂停时长。"""
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name='sla_timer', verbose_name="任务")
    paused_at = models.DateTimeField(null=True, blank=True, verbose_name="暂停时间")
    total_paused_seconds = models.PositiveIntegerField(default=0, verbose_name="累计暂停秒数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "SLA计时器"
        verbose_name_plural = "SLA计时器"

    def __str__(self):
        return f"SLA timer for task {self.task_id}"


class SystemSetting(models.Model):
    """简单的键值配置存储，支持 SLA 等后台可调参数。"""
    key = models.CharField(max_length=100, unique=True, verbose_name="键")
    value = models.CharField(max_length=200, blank=True, verbose_name="值")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ['key']
        verbose_name = "系统设置"
        verbose_name_plural = "系统设置"

    def __str__(self):
        return f"{self.key}={self.value}"


def default_export_expiry():
    return timezone.now() + timedelta(days=3)


class ExportJob(models.Model):
    """导出任务队列：记录状态与生成的文件路径。"""
    STATUS_CHOICES = [
        ('pending', '待处理 / Pending'),
        ('running', '处理中 / Running'),
        ('done', '完成 / Done'),
        ('failed', '失败 / Failed'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='export_jobs', verbose_name="用户")
    export_type = models.CharField(max_length=50, verbose_name="导出类型")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    progress = models.IntegerField(default=0, verbose_name="进度(%)")
    file_path = models.CharField(max_length=500, blank=True, verbose_name="文件路径")
    message = models.TextField(blank=True, verbose_name="消息")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    expires_at = models.DateTimeField(default=default_export_expiry, verbose_name="过期时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "导出任务"
        verbose_name_plural = "导出任务"

    def __str__(self):
        return f"{self.export_type} {self.status}"


class UserPreference(models.Model):
    """用户偏好，存储仪表卡片等设置。"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferences', verbose_name="用户")
    data = models.JSONField(default=dict, blank=True, verbose_name="偏好数据")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "用户偏好"
        verbose_name_plural = "用户偏好"


class TaskHistory(models.Model):
    """任务变更历史：状态、截止时间、指派人等变更记录。"""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='histories', verbose_name="任务")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='task_histories', verbose_name="操作人")
    field = models.CharField(max_length=50, verbose_name="变更字段")
    old_value = models.CharField(max_length=200, blank=True, verbose_name="旧值")
    new_value = models.CharField(max_length=200, blank=True, verbose_name="新值")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "任务变更历史"
        verbose_name_plural = "任务变更历史"

    def __str__(self):
        return f"{self.task_id} {self.field}: {self.old_value} -> {self.new_value}"


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


class TaskTemplateVersion(models.Model):
    """任务模板版本：按项目保存任务标题/内容/链接模板，支持共享与版本记录。"""
    name = models.CharField(max_length=200, verbose_name="模板名称")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='task_templates', verbose_name="适用项目")
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True, verbose_name="适用角色")
    title = models.CharField(max_length=200, verbose_name="任务标题")
    content = models.TextField(blank=True, verbose_name="任务内容")
    url = models.URLField(blank=True, verbose_name="链接")
    is_shared = models.BooleanField(default=True, verbose_name="是否共享")
    version = models.PositiveIntegerField(default=1, verbose_name="版本号")
    usage_count = models.PositiveIntegerField(default=0, verbose_name="使用次数")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='task_template_versions', verbose_name="创建人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['name', '-version']
        unique_together = ('name', 'project', 'role', 'version')
        verbose_name = "任务模板版本"
        verbose_name_plural = "任务模板版本"

    def __str__(self):
        target = self.project.name if self.project else 'global'
        role = dict(Profile.ROLE_CHOICES).get(self.role, self.role or 'all')
        return f"{self.name} ({target}/{role}) v{self.version}"


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('task_assigned', '任务分配'),
        ('task_updated', '任务更新'),
        ('task_mention', '任务提及'),
        ('sla_reminder', 'SLA提醒'),
        ('project_update', '项目更新'),
        ('report_reminder', '日报提醒'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="用户")
    title = models.CharField(max_length=200, verbose_name="标题")
    message = models.TextField(verbose_name="内容")
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, verbose_name="类型")
    is_read = models.BooleanField(default=False, verbose_name="是否已读")
    data = models.JSONField(default=dict, blank=True, verbose_name="数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "通知"
        verbose_name_plural = "通知"

    def __str__(self):
        return f"{self.user.username} - {self.title}"


class PermissionMatrix(models.Model):
    ROLE_CHOICES = Profile.ROLE_CHOICES
    PERMISSION_CHOICES = [
        ('view_project', '查看项目'),
        ('edit_project', '编辑项目'),
        ('delete_project', '删除项目'),
        ('manage_members', '管理成员'),
        ('view_reports', '查看报表'),
        ('manage_tasks', '管理任务'),
        ('view_tasks', '查看任务'),
        ('manage_phases', '管理阶段'),
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, verbose_name="角色")
    permission = models.CharField(max_length=50, choices=PERMISSION_CHOICES, verbose_name="权限标识")
    description = models.CharField(max_length=200, blank=True, verbose_name="描述")
    is_active = models.BooleanField(default=True, verbose_name="是否启用")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        unique_together = ('role', 'permission')
        verbose_name = "权限矩阵"
        verbose_name_plural = "权限矩阵"

    def __str__(self):
        return f"{self.get_role_display()} - {self.get_permission_display()}"


class ProjectMemberPermission(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='member_permissions', verbose_name="项目")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_permissions', verbose_name="用户")
    permissions = models.JSONField(default=list, blank=True, help_text="权限列表，如 ['view_tasks', 'manage_tasks']", verbose_name="权限列表")
    granted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='granted_permissions', verbose_name="授权人")
    granted_at = models.DateTimeField(auto_now_add=True, verbose_name="授权时间")

    class Meta:
        unique_together = ('project', 'user')
        verbose_name = "项目成员权限"
        verbose_name_plural = "项目成员权限"

    def __str__(self):
        return f"{self.user.username} in {self.project.name}"
