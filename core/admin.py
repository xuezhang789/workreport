from django.contrib import admin
from .models import (
    Profile,
    SystemSetting,
    ExportJob,
    UserPreference,
    Notification,
)

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'position')

@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'updated_at')
    search_fields = ('key', 'value')

@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ('user', 'export_type', 'status', 'progress', 'created_at')
    list_filter = ('status', 'export_type', 'created_at')
    search_fields = ('user__username',)

@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__username',)

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('title', 'message', 'user__username')

