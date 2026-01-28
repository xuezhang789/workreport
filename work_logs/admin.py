from django.contrib import admin
from .models import (
    DailyReport,
    ReportMiss,
    RoleTemplate,
    ReminderRule,
    ReportTemplateVersion
)

@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'role', 'project', 'status')
    list_filter = ('role', 'date', 'status')
    search_fields = ('user__username', 'project')

@admin.register(ReportMiss)
class ReportMissAdmin(admin.ModelAdmin):
    list_display = ('user', 'project', 'role', 'date', 'notified_at', 'resolved_at')
    list_filter = ('date', 'role')
    search_fields = ('user__username', 'project__name', 'project__code')

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

@admin.register(ReportTemplateVersion)
class ReportTemplateVersionAdmin(admin.ModelAdmin):
    list_display = ('name', 'version', 'role', 'project', 'is_shared', 'created_by', 'created_at')
    list_filter = ('is_shared', 'role', 'project')
    search_fields = ('name', 'content')
