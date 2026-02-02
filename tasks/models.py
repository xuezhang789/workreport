from django.db import models
from django.contrib.auth.models import User
from core.models import Profile
from core.constants import TaskStatus, TaskCategory
from projects.models import Project

class Task(models.Model):
    """
    任务模型：核心业务对象。
    包含标题、内容、状态、优先级、负责人、截止时间等关键信息。
    """
    STATUS_CHOICES = TaskStatus.choices
    CATEGORY_CHOICES = TaskCategory.choices

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
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=TaskCategory.TASK, verbose_name="分类")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=TaskStatus.TODO, verbose_name="状态")
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
            models.Index(fields=['category']),
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

    def save(self, *args, **kwargs):
        # 如果是新建的 BUG 类型任务且状态为默认的 TODO，自动修正为 NEW
        if not self.pk and self.category == TaskCategory.BUG and self.status == TaskStatus.TODO:
            self.status = TaskStatus.NEW
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} -> {self.user.username}"


class TaskComment(models.Model):
    """
    任务评论：支持用户在任务下留言，支持 @提及用户。
    """
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
    """
    任务附件：支持上传文件或添加外部链接。
    """
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


class TaskTemplateVersion(models.Model):
    """
    任务模板版本：按项目或角色保存任务模板（标题/内容/链接），支持共享与版本控制。
    """
    name = models.CharField(max_length=200, verbose_name="模板名称")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='task_templates', verbose_name="适用项目")
    role = models.CharField(max_length=10, choices=Profile.ROLE_CHOICES, null=True, blank=True, verbose_name="适用角色")
    title = models.CharField(max_length=200, verbose_name="任务标题")
    content = models.TextField(blank=True, verbose_name="任务内容")
    url = models.URLField(blank=True, verbose_name="链接")
    is_shared = models.BooleanField(default=True, verbose_name="是否共享")
    version = models.PositiveIntegerField(default=1, verbose_name="版本号")
    usage_count = models.PositiveIntegerField(default=0, verbose_name="使用次数")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks_template_versions', verbose_name="创建人")
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
