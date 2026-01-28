from django.contrib import admin
from .models import (
    Project,
    ProjectPhaseConfig,
    ProjectPhaseChangeLog,
    ProjectMemberPermission,
    ProjectAttachment
)

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'owner', 'start_date', 'end_date', 'is_active')
    search_fields = ('name', 'code', 'description')
    list_filter = ('start_date', 'end_date', 'is_active')

@admin.register(ProjectPhaseConfig)
class ProjectPhaseConfigAdmin(admin.ModelAdmin):
    list_display = ('phase_name', 'progress_percentage', 'order_index', 'is_active')
    list_editable = ('order_index', 'is_active')
    ordering = ('order_index',)

@admin.register(ProjectPhaseChangeLog)
class ProjectPhaseChangeLogAdmin(admin.ModelAdmin):
    list_display = ('project', 'old_phase', 'new_phase', 'changed_by', 'changed_at')
    list_filter = ('project', 'changed_at')
    readonly_fields = ('project', 'old_phase', 'new_phase', 'changed_by', 'changed_at')

@admin.register(ProjectMemberPermission)
class ProjectMemberPermissionAdmin(admin.ModelAdmin):
    list_display = ('project', 'user', 'granted_by', 'granted_at')
    search_fields = ('project__name', 'user__username')
    list_filter = ('project',)

@admin.register(ProjectAttachment)
class ProjectAttachmentAdmin(admin.ModelAdmin):
    list_display = ('project', 'uploaded_by', 'original_filename', 'created_at')
    search_fields = ('project__name', 'original_filename')
