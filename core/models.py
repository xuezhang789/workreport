from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from datetime import timedelta

# --- 现有模型 ---

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

    # 人事管理字段
    EMPLOYMENT_STATUS_CHOICES = [('active', '在职'), ('terminated', '离职')]
    employment_status = models.CharField(max_length=20, choices=EMPLOYMENT_STATUS_CHOICES, default='active', verbose_name="是否在职")
    hire_date = models.DateField(null=True, blank=True, verbose_name="入职时间")
    probation_months = models.PositiveIntegerField(default=3, verbose_name="试用时长(月)") # 1-6
    probation_salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="试用薪资")
    official_salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="正式薪资")
    CURRENCY_CHOICES = [('CNY', 'CNY'), ('USDT', 'USDT')]
    salary_currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='CNY', verbose_name="货币单位")

    # Payment Info
    usdt_address = models.CharField(max_length=255, blank=True, null=True, verbose_name="USDT 地址")
    usdt_qr_code = models.ImageField(upload_to='payment_qr/%Y/%m/', blank=True, null=True, verbose_name="USDT 收款二维码")
    email_verified = models.BooleanField(default=False, verbose_name="邮箱已验证")

    intermediary_company = models.CharField(max_length=255, blank=True, null=True, verbose_name="中介公司")
    intermediary_fee_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="中介费用")
    intermediary_fee_currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='CNY', verbose_name="中介费用货币单位")
    resignation_date = models.DateField(null=True, blank=True, verbose_name="离职时间")
    hr_note = models.CharField(max_length=500, blank=True, verbose_name="备注")

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"
        indexes = [
            models.Index(fields=['intermediary_company', 'intermediary_fee_currency'], name='idx_intermediary'),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_position_display()}"

    @property
    def avatar_url(self):
        try:
            return self.user.preferences.data.get('profile', {}).get('avatar_data_url')
        except (AttributeError, ObjectDoesNotExist, TypeError):
            return None


class SalaryHistory(models.Model):
    """记录员工薪资变更历史"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='salary_history', verbose_name="用户")
    old_probation = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="原试用薪资")
    new_probation = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="新试用薪资")
    old_official = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="原正式薪资")
    new_official = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="新正式薪资")
    currency = models.CharField(max_length=10, default='CNY', verbose_name="货币")
    reason = models.CharField(max_length=255, blank=True, verbose_name="变更原因")
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='salary_changes_made', verbose_name="操作人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="变更时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "薪资历史"
        verbose_name_plural = "薪资历史"


class Contract(models.Model):
    """员工劳动合同"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contracts', verbose_name="用户")
    file = models.FileField(upload_to='contracts/%Y/%m/', verbose_name="合同文件")
    original_filename = models.CharField(max_length=255, verbose_name="原始文件名")
    start_date = models.DateField(null=True, blank=True, verbose_name="开始日期")
    end_date = models.DateField(null=True, blank=True, verbose_name="结束日期")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="上传人")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "劳动合同"
        verbose_name_plural = "劳动合同"


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


class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('task_assigned', '任务分配'),
        ('task_updated', '任务更新'),
        ('task_mention', '任务提及'),
        ('sla_reminder', 'SLA提醒'),
        ('project_update', '项目更新'),
        ('report_reminder', '日报提醒'),
    ]

    PRIORITY_CHOICES = [
        ('high', '高 / High'),
        ('normal', '普通 / Normal'),
        ('low', '低 / Low'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications', verbose_name="用户")
    title = models.CharField(max_length=200, verbose_name="标题")
    message = models.TextField(verbose_name="内容")
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, verbose_name="类型")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal', verbose_name="优先级")
    is_read = models.BooleanField(default=False, verbose_name="是否已读")
    is_pushed = models.BooleanField(default=False, verbose_name="是否已推送")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    data = models.JSONField(default=dict, blank=True, verbose_name="数据")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "通知"
        verbose_name_plural = "通知"
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['created_at']),
            models.Index(fields=['priority']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.title}"


# class PermissionMatrix(models.Model):
#     """
#     Deprecated: Replaced by RBAC system (Role, Permission, RolePermission).
#     Kept for migration reference.
#     已弃用：被 RBAC 系统（Role, Permission, RolePermission）替代。
#     保留以供迁移参考。
#     """
#     ROLE_CHOICES = Profile.ROLE_CHOICES
#     PERMISSION_CHOICES = [
#         ('view_project', '查看项目'),
#         ('edit_project', '编辑项目'),
#         ('delete_project', '删除项目'),
#         ('manage_members', '管理成员'),
#         ('view_reports', '查看报表'),
#         ('manage_tasks', '管理任务'),
#         ('view_tasks', '查看任务'),
#         ('manage_phases', '管理阶段'),
#     ]
#
#     role = models.CharField(max_length=10, choices=ROLE_CHOICES, verbose_name="角色")
#     permission = models.CharField(max_length=50, choices=PERMISSION_CHOICES, verbose_name="权限标识")
#     description = models.CharField(max_length=200, blank=True, verbose_name="描述")
#     is_active = models.BooleanField(default=True, verbose_name="是否启用")
#     created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
#
#     class Meta:
#         unique_together = ('role', 'permission')
#         verbose_name = "权限矩阵"
#         verbose_name_plural = "权限矩阵"
#
#     def __str__(self):
#         return f"{self.get_role_display()} - {self.get_permission_display()}"


# --- 新 RBAC 模型 ---

class Permission(models.Model):
    """RBAC 权限原子定义"""
    code = models.CharField(max_length=100, unique=True, verbose_name="权限代码", help_text="例如：project.view")
    name = models.CharField(max_length=100, verbose_name="权限名称")
    group = models.CharField(max_length=50, blank=True, verbose_name="权限分组", help_text="例如：project, task")
    description = models.CharField(max_length=255, blank=True, verbose_name="描述")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "RBAC权限"
        verbose_name_plural = "RBAC权限"
        ordering = ['group', 'code']

    def __str__(self):
        return f"{self.name} ({self.code})"


class Role(models.Model):
    """RBAC 角色定义，支持继承"""
    code = models.CharField(max_length=100, unique=True, verbose_name="角色代码", help_text="例如：project_manager")
    name = models.CharField(max_length=100, verbose_name="角色名称")
    description = models.TextField(blank=True, verbose_name="描述")
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children', verbose_name="父角色")
    permissions = models.ManyToManyField(Permission, through='RolePermission', related_name='roles', verbose_name="权限集合")
    is_system = models.BooleanField(default=False, verbose_name="系统角色", help_text="系统角色不可删除")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "RBAC角色"
        verbose_name_plural = "RBAC角色"

    def __str__(self):
        return f"{self.name} ({self.code})"


class RolePermission(models.Model):
    """角色与权限的关联表"""
    role = models.ForeignKey(Role, on_delete=models.CASCADE)
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('role', 'permission')
        verbose_name = "RBAC角色权限关联"
        verbose_name_plural = "RBAC角色权限关联"


class UserRole(models.Model):
    """用户与角色的关联，支持资源范围（Scope）"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rbac_roles', verbose_name="用户")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='users', verbose_name="角色")
    # scope definition: 'global' (None) or 'project:1', 'task:100', etc.
    scope = models.CharField(max_length=100, null=True, blank=True, verbose_name="资源范围", help_text="格式: resource_type:id，为空表示全局")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 用户可以在不同的范围内拥有相同的角色，或者在相同的范围内拥有不同的角色。
        unique_together = ('user', 'role', 'scope')
        indexes = [
            models.Index(fields=['user', 'scope']),  # 快速查找“用户在此范围内拥有哪些角色？”
            models.Index(fields=['scope']),          # “谁在此范围内拥有角色？”
        ]
        verbose_name = "RBAC用户角色"
        verbose_name_plural = "RBAC用户角色"

    def __str__(self):
        scope_str = self.scope if self.scope else "Global"
        return f"{self.user.username} - {self.role.name} [{scope_str}]"

from django.db import models
from django.contrib.auth.models import User
import uuid

class ChunkedUpload(models.Model):
    """
    分片上传追踪，用于支持断点续传。
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chunked_uploads')
    filename = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    uploaded_size = models.BigIntegerField(default=0)
    chunk_count = models.IntegerField(default=0)
    status = models.CharField(max_length=20, default='uploading', choices=[
        ('uploading', 'Uploading'),
        ('complete', 'Complete'),
        ('failed', 'Failed')
    ])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Store temp file path or use a convention based on ID
    temp_path = models.CharField(max_length=512, blank=True)

    class Meta:
        verbose_name = "分片上传"
        verbose_name_plural = "分片上传"


class Invitation(models.Model):
    """邀请码模型"""
    STATUS_CHOICES = [
        ('unused', '未使用 / Unused'),
        ('used', '已使用 / Used'),
        ('expired', '已过期 / Expired'),
    ]

    code = models.CharField(max_length=50, unique=True, verbose_name="邀请码", db_index=True)
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='generated_invitations', verbose_name="邀请人")
    email = models.EmailField(blank=True, null=True, verbose_name="受邀邮箱", help_text="可选，指定特定邮箱")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unused', verbose_name="状态")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    expires_at = models.DateTimeField(verbose_name="过期时间")
    used_at = models.DateTimeField(null=True, blank=True, verbose_name="使用时间")
    
    registered_user = models.OneToOneField(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='invitation_used', 
        verbose_name="注册用户"
    )

    class Meta:
        verbose_name = "邀请码"
        verbose_name_plural = "邀请码"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.code} ({self.get_status_display()})"

    @property
    def is_valid(self):
        return self.status == 'unused' and self.expires_at > timezone.now()

    def save(self, *args, **kwargs):
        if not self.expires_at:
            # 默认 7 天有效期
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)
