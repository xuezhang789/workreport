from django.contrib import admin
from .models import (
    Task,
    TaskComment,
    TaskAttachment,
    TaskSlaTimer,
    TaskTemplateVersion
)

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'project', 'status', 'priority', 'created_at', 'completed_at', 'due_at')
    list_filter = ('status', 'priority', 'project', 'created_at')
    search_fields = ('title', 'user__username', 'project__name')

@admin.register(TaskComment)
class TaskCommentAdmin(admin.ModelAdmin):
    list_display = ('task', 'user', 'created_at')
    search_fields = ('task__title', 'user__username', 'content')

@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ('task', 'user', 'url', 'created_at')
    search_fields = ('task__title', 'user__username', 'url')

@admin.register(TaskSlaTimer)
class TaskSlaTimerAdmin(admin.ModelAdmin):
    list_display = ('task', 'paused_at', 'total_paused_seconds', 'created_at')
    search_fields = ('task__title', 'task__id')

@admin.register(TaskTemplateVersion)
class TaskTemplateVersionAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'role', 'project', 'is_shared', 'created_by', 'created_at')
    list_filter = ('is_shared', 'role', 'project')
    search_fields = ('name', 'title', 'content')
