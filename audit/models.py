from django.db import models
from django.contrib.auth.models import User
from projects.models import Project
from tasks.models import Task

class AuditLog(models.Model):
    """
    统一审计日志：记录所有关键操作（创建、更新、删除、访问、上传等）。
    支持存储详细的变更差异 (diff) 和上下文信息。
    """
    ACTION_CHOICES = [
        ('login', '登录 / Login'),
        ('logout', '登出 / Logout'),
        ('create', '创建 / Create'),
        ('update', '更新 / Update'),
        ('delete', '删除 / Delete'),
        ('access', '访问 / Access'),
        ('export', '导出 / Export'),
        ('upload', '上传 / Upload'),
        ('other', '其他 / Other'),
    ]
    
    RESULT_CHOICES = [
        ('success', '成功 / Success'),
        ('failure', '失败 / Failure'),
    ]

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs', verbose_name="用户")
    operator_name = models.CharField(max_length=150, blank=True, verbose_name="操作人姓名")
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="动作")
    result = models.CharField(max_length=10, choices=RESULT_CHOICES, default='success', verbose_name="结果")
    
    ip = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP地址")
    
    # Target Entity Info
    target_type = models.CharField(max_length=100, blank=True, verbose_name="对象类型") # e.g. Task, Project
    target_id = models.CharField(max_length=100, blank=True, verbose_name="对象ID")
    target_label = models.CharField(max_length=255, blank=True, verbose_name="对象名称") # Snapshot of title/name
    
    # Detailed Info
    summary = models.TextField(blank=True, verbose_name="摘要") # Readable summary
    details = models.JSONField(default=dict, blank=True, verbose_name="详情") # Stores diff, context, ua, path, etc.
    
    # Context
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs', verbose_name="关联项目")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs', verbose_name="关联任务")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="记录时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"
        indexes = [
            models.Index(fields=['target_type', 'target_id']),
            models.Index(fields=['action']),
            models.Index(fields=['result']),
            models.Index(fields=['created_at']),
            models.Index(fields=['project']),
            models.Index(fields=['task']),
        ]

    def __str__(self):
        who = self.operator_name or (self.user.username if self.user else 'anonymous')
        return f"[{self.result.upper()}] {self.action} {self.target_type}#{self.target_id} by {who}"


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
