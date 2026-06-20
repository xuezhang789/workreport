from datetime import time
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.models import Profile
from projects.models import Project
from django.db.models import Q

class ReminderRule(models.Model):
    """日报提醒规则：按项目/角色配置提醒时间与渠道。"""
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.CASCADE, related_name='reminder_rules', verbose_name="项目")
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
    """
    日报模型：记录用户每日工作内容、计划和问题。
    字段根据角色动态展示。
    """
    ROLE_CHOICES = Profile.ROLE_CHOICES
    STATUS_CHOICES = [
        ('draft', '草稿 / Draft'),
        ('submitted', '已提交 / Submitted'),
    ]
    ROLE_CONTENT_FIELDS = {
        'dev': ('today_work', 'progress_issues', 'tomorrow_plan'),
        'qa': ('testing_scope', 'testing_progress', 'bug_summary', 'testing_tomorrow'),
        'pm': ('product_today', 'product_coordination', 'product_tomorrow'),
        'ui': ('ui_today', 'ui_feedback', 'ui_tomorrow'),
        'ops': ('ops_today', 'ops_monitoring', 'ops_tomorrow'),
        'mgr': ('mgr_progress', 'mgr_risks', 'mgr_tomorrow'),
    }
    CONTENT_FIELD_NAMES = tuple(
        field_name
        for role_fields in ROLE_CONTENT_FIELDS.values()
        for field_name in role_fields
    )
    CURRENT_CONTENT_SCHEMA_VERSION = 2
    CONTENT_RESERVED_KEYS = ('_legacy_project', '_extra')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_reports', verbose_name="用户")
    date = models.DateField(verbose_name="日期")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, verbose_name="角色")
    projects = models.ManyToManyField(Project, blank=True, related_name='reports', verbose_name="关联项目")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted', verbose_name="状态")
    content = models.JSONField(default=dict, blank=True, verbose_name="结构化日报内容")
    content_schema_version = models.PositiveSmallIntegerField(default=CURRENT_CONTENT_SCHEMA_VERSION, verbose_name="内容 Schema 版本")

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

    @staticmethod
    def _normalize_known_content_value(value):
        if value is None:
            return ''
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    @classmethod
    def normalize_content(cls, role, content):
        """
        Normalize report content into the current JSON contract.

        Known business fields remain at the root for query compatibility.
        Unknown extension fields are preserved under ``_extra`` so schema drift
        is explicit and reversible.
        """
        if not isinstance(content, dict):
            return {}

        allowed_root_keys = set(cls.CONTENT_FIELD_NAMES) | {'_legacy_project', '_extra'}
        normalized = {}
        extra = {}

        for key, value in content.items():
            if key == '_extra':
                if isinstance(value, dict):
                    for extra_key, extra_value in value.items():
                        if extra_value not in (None, ''):
                            extra[extra_key] = extra_value
                elif value not in (None, ''):
                    extra['value'] = value
                continue

            if key in allowed_root_keys:
                normalized_value = cls._normalize_known_content_value(value)
                if normalized_value:
                    normalized[key] = normalized_value
            elif value not in (None, ''):
                extra[key] = value

        if extra:
            normalized['_extra'] = extra

        return normalized

    @classmethod
    def has_role_content(cls, role, content):
        normalized = cls.normalize_content(role, content)
        return any(normalized.get(field_name) for field_name in cls.ROLE_CONTENT_FIELDS.get(role, ()))

    @classmethod
    def validate_content_payload(cls, role, content, require_role_content=False):
        errors = []
        if role not in dict(cls.ROLE_CHOICES):
            errors.append("请选择有效的角色")
            return errors
        if require_role_content and not cls.has_role_content(role, content):
            errors.append("请填写与角色对应的内容，至少一项")
        return errors

    @classmethod
    def content_search_query(cls, query):
        search = Q()
        for field_name in cls.CONTENT_FIELD_NAMES:
            search |= Q(**{f'content__{field_name}__icontains': query})
        return search

    def role_content(self):
        fields = self.ROLE_CONTENT_FIELDS.get(self.role, ())
        return {field_name: getattr(self, field_name) for field_name in fields}

    @property
    def summary(self):
        """
        返回第一个非空的摘要字段，用于列表展示或导出。
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

    def clean(self):
        super().clean()
        errors = self.validate_content_payload(
            self.role,
            self.content,
            require_role_content=self.status == 'submitted',
        )
        if errors:
            raise ValidationError({'content': errors})

    def save(self, *args, **kwargs):
        self.content = self.normalize_content(self.role, self.content)
        self.content_schema_version = self.CURRENT_CONTENT_SCHEMA_VERSION
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            update_fields = set(update_fields)
            update_fields.update({'content', 'content_schema_version'})
            kwargs['update_fields'] = update_fields
        super().save(*args, **kwargs)


def _daily_report_content_property(field_name):
    def getter(instance):
        return (instance.content or {}).get(field_name, '')

    def setter(instance, value):
        content = dict(instance.content or {})
        if value not in (None, ''):
            content[field_name] = value
        else:
            content.pop(field_name, None)
        instance.content = content

    return property(getter, setter)


for _content_field_name in DailyReport.CONTENT_FIELD_NAMES:
    setattr(DailyReport, _content_field_name, _daily_report_content_property(_content_field_name))

DailyReport.project = _daily_report_content_property('_legacy_project')


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


class Attendance(models.Model):
    """
    考勤记录：与日报关联，用户每日提交日报即视为当日已考勤。
    """
    STATUS_CHOICES = [
        ('present', '出勤 / Present'),
        ('absent', '缺勤 / Absent'),
        ('leave', '请假 / Leave'),
        ('makeup', '补卡 / Make-up'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendances', verbose_name="用户")
    date = models.DateField(verbose_name="日期")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present', verbose_name="状态")
    report = models.OneToOneField('DailyReport', on_delete=models.SET_NULL, null=True, blank=True, related_name='attendance_record', verbose_name="关联日报")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        unique_together = ('user', 'date')
        ordering = ['-date']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['date']),
            models.Index(fields=['status']),
        ]
        verbose_name = "考勤记录"
        verbose_name_plural = "考勤记录"

    def __str__(self):
        return f"{self.user.username} - {self.date} - {self.get_status_display()}"


from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=DailyReport)
def update_attendance_from_report(sender, instance, created, **kwargs):
    """
    日报提交触发考勤记录。
    如果状态为“已提交”，则标记为出勤。
    """
    if instance.status == 'submitted':
        Attendance.objects.update_or_create(
            user=instance.user,
            date=instance.date,
            defaults={
                'status': 'present',
                'report': instance,
            }
        )
