from django.contrib import admin
from .models import (
    Profile,
    DailyReport,
    Project,
    AuditLog,
    Task,
    TaskComment,
    TaskAttachment,
    RoleTemplate,
    ReminderRule,
    ReportMiss,
    TaskSlaTimer,
    TaskHistory,
)

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'position')

@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'role', 'project', 'status')
    list_filter = ('role', 'date', 'status')
    search_fields = ('user__username', 'project')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'owner', 'start_date', 'end_date', 'is_active')
    search_fields = ('name', 'code', 'description')
    list_filter = ('start_date', 'end_date', 'is_active')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'path', 'method', 'created_at')
    list_filter = ('action', 'method', 'created_at')
    search_fields = ('path', 'extra', 'user__username')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'project', 'status', 'created_at', 'completed_at', 'due_at')
    list_filter = ('status', 'project', 'created_at')
    search_fields = ('title', 'user__username', 'project__name')


@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ('task', 'user', 'created_at')
    search_fields = ('task__title', 'user__username', 'content')


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ('task', 'user', 'url', 'created_at')
    search_fields = ('task__title', 'user__username', 'url')


@admin.register(RoleTemplate)
class RoleTemplateAdmin(admin.ModelAdmin):
    list_display = ('role', 'is_active', 'sort_order', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('role', 'hint', 'sample_md')
    ordering = ('sort_order', 'role')


@admin.register(ReminderRule)
class ReminderRuleAdmin(admin.ModelAdmin):
    list_display = ('project', 'role', 'cutoff_time', 'channel', 'enabled', 'weekdays_only')
    list_filter = ('enabled', 'weekdays_only', 'channel')
    search_fields = ('project__name', 'project__code', 'role')


@admin.register(ReportMiss)
class ReportMissAdmin(admin.ModelAdmin):
    list_display = ('user', 'project', 'role', 'date', 'notified_at', 'resolved_at')
    list_filter = ('date', 'role')
    search_fields = ('user__username', 'project__name', 'project__code')


@admin.register(TaskSlaTimer)
class TaskSlaTimerAdmin(admin.ModelAdmin):
    list_display = ('task', 'paused_at', 'total_paused_seconds', 'created_at')
    search_fields = ('task__title', 'task__id')


@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ('task', 'field', 'old_value', 'new_value', 'user', 'created_at')
    list_filter = ('field',)
    search_fields = ('task__title', 'user__username', 'old_value', 'new_value')
