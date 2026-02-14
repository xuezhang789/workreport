from django.urls import path
from . import views_preferences
from . import views_teams
from . import views_notifications
from . import daily_report_views
from . import statistics_views
from . import export_views
from . import template_views
from . import audit_views
from . import search_views
from . import notification_views
from . import views_hr

app_name = 'reports'

urlpatterns = [
    path('new/', daily_report_views.daily_report_create, name='daily_report_create'),
    path('batch-create/', daily_report_views.daily_report_batch_create, name='daily_report_batch_create'),
    path('my/', daily_report_views.my_reports, name='my_reports'),
    path('my/export/', export_views.my_reports_export, name='my_reports_export'),
    path('my/<int:pk>/', daily_report_views.report_detail, name='report_detail'),
    path('my/<int:pk>/submit/', daily_report_views.report_submit, name='report_submit'),
    path('templates/roles/', template_views.role_template_manage, name='role_template_manage'),
    path('api/role-template/', template_views.role_template_api, name='role_template_api'),
    # path('api/projects/', views.project_search_api, name='project_search_api'), # Moved to projects app
    # path('api/users/', views.user_search_api, name='user_search_api'), # Moved to core app
    # path('api/check-username/', views.username_check_api, name='username_check_api'), # Moved to core app
    path('workbench/', statistics_views.workbench, name='workbench'),
    path('stats/', statistics_views.stats, name='stats'),
    path('performance/', statistics_views.performance_board, name='performance_board'),
    path('performance/export/', export_views.performance_export, name='performance_export'),
    path('admin/reports/', daily_report_views.admin_reports, name='admin_reports'),
    path('admin/reports/export/', export_views.admin_reports_export, name='admin_reports_export'),
    path('my/<int:pk>/edit/', daily_report_views.report_edit, name='report_edit'),
    # Projects moved to projects app
    
    path('audit/', audit_views.audit_logs, name='audit_logs'),
    path('audit/export/', export_views.audit_logs_export, name='audit_logs_export'),
    path('templates/center/', template_views.template_center, name='template_center'),
    path('templates/api/apply/', template_views.template_apply_api, name='template_apply_api'),
    path('templates/api/recommend/', template_views.template_recommend_api, name='template_recommend_api'),
    # path('export/jobs/<int:job_id>/', views.export_job_status, name='export_job_status'), # Moved to core app
    # path('export/jobs/<int:job_id>/download/', views.export_job_download, name='export_job_download'), # Moved to core app
    path('prefs/', views_preferences.preference_get_api, name='preference_get_api'),
    path('prefs/save/', views_preferences.preference_save_api, name='preference_save_api'),

    # API
    # path('api/projects/<int:pk>/', views.api_project_detail, name='api_project_detail'), # Moved
    path('api/audit-logs/', audit_views.api_audit_logs, name='api_audit_logs'),
    
    # Phase Management - Moved
    
    # Project Phase Actions - Moved
    
    # Team Management
    path('teams/', views_teams.teams_list, name='teams'),
    path('teams/<int:user_id>/role/', views_teams.team_member_update_role, name='team_member_update_role'),
    path('teams/<int:user_id>/project/add/', views_teams.team_member_add_project, name='team_member_add_project'),
    path('teams/<int:user_id>/project/<int:project_id>/remove/', views_teams.team_member_remove_project, name='team_member_remove_project'),
    path('api/admin/members/<int:user_id>/hr-info/', views_hr.update_hr_info, name='api_hr_info_update'),

    # Project Attachments - Moved

    # Notifications
    path('api/notifications/list/', views_notifications.notification_list_api, name='notification_list_api'),
    path('api/notifications/mark-read/', views_notifications.mark_read_api, name='mark_all_read_api'),
    path('api/notifications/<int:pk>/mark-read/', views_notifications.mark_read_api, name='mark_read_api'),
    path('api/notifications/unread-count/', notification_views.get_unread_count, name='notification_unread_count'), # Added
    path('notifications/', notification_views.notification_list, name='notification_list'), # Updated to new view


    # Task Attachments - Moved to tasks app
    
    # Global Search
    path('search/', search_views.global_search, name='global_search'),
]
