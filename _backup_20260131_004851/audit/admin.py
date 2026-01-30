from django.contrib import admin
from .models import AuditLog, TaskHistory

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'user', 'target_type', 'target_id', 'result', 'created_at')
    list_filter = ('action', 'result', 'created_at')
    search_fields = ('summary', 'user__username', 'target_label', 'target_id')

@admin.register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
    list_display = ('task', 'field', 'old_value', 'new_value', 'user', 'created_at')
    list_filter = ('field',)
    search_fields = ('task__title', 'user__username', 'old_value', 'new_value')
