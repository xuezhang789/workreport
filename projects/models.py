from datetime import time
from django.db import models
from django.contrib.auth.models import User
from core.models import Profile

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
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects_phase_logs', verbose_name="变更人")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="变更时间")

    class Meta:
        ordering = ['-changed_at']
        verbose_name = "项目阶段变更日志"
        verbose_name_plural = "项目阶段变更日志"

    def __str__(self):
        return f"{self.project.name}: {self.old_phase} -> {self.new_phase}"


class ProjectAttachment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='attachments', verbose_name="项目")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects_attachments', verbose_name="上传人")
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


class ProjectMemberPermission(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='member_permissions', verbose_name="项目")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='projects_permissions', verbose_name="用户")
    permissions = models.JSONField(default=list, blank=True, help_text="权限列表，如 ['view_tasks', 'manage_tasks']", verbose_name="权限列表")
    granted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='projects_granted_permissions', verbose_name="授权人")
    granted_at = models.DateTimeField(auto_now_add=True, verbose_name="授权时间")

    class Meta:
        unique_together = ('project', 'user')
        verbose_name = "项目成员权限"
        verbose_name_plural = "项目成员权限"

    def __str__(self):
        return f"{self.user.username} in {self.project.name}"
