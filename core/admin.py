from django.contrib import admin
from .models import (
    Profile,
    SystemSetting,
    ExportJob,
    UserPreference,
    Notification,
    NotificationDelivery,
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


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ('notification', 'channel', 'status', 'attempts', 'created_at', 'sent_at')
    list_filter = ('channel', 'status', 'created_at')
    search_fields = ('notification__title', 'notification__user__username', 'last_error')
    readonly_fields = (
        'notification', 'channel', 'status', 'payload', 'attempts',
        'next_retry_at', 'last_error', 'sent_at', 'created_at', 'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
