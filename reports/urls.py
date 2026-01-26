from django.urls import path
from . import views
from . import views_preferences
from . import views_teams

app_name = 'reports'

urlpatterns = [
    path('new/', views.daily_report_create, name='daily_report_create'),
    path('my/', views.my_reports, name='my_reports'),
    path('my/export/', views.my_reports_export, name='my_reports_export'),
    path('my/<int:pk>/', views.report_detail, name='report_detail'),
    path('my/<int:pk>/submit/', views.report_submit, name='report_submit'),
    path('templates/roles/', views.role_template_manage, name='role_template_manage'),
    path('api/role-template/', views.role_template_api, name='role_template_api'),
    path('api/projects/', views.project_search_api, name='project_search_api'),
    path('api/users/', views.user_search_api, name='user_search_api'),
    path('api/check-username/', views.username_check_api, name='username_check_api'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/bulk/', views.task_bulk_action, name='task_bulk_action'),
    path('tasks/export/', views.task_export, name='task_export'),
    path('tasks/export/selected/', views.task_export_selected, name='task_export_selected'),
    path('tasks/<int:pk>/complete/', views.task_complete, name='task_complete'),
    path('tasks/<int:pk>/view/', views.task_view, name='task_view'),
    path('tasks/admin/', views.admin_task_list, name='admin_task_list'),
    path('tasks/admin/bulk/', views.admin_task_bulk_action, name='admin_task_bulk_action'),
    path('tasks/admin/new/', views.admin_task_create, name='admin_task_create'),
    path('tasks/<int:pk>/edit/', views.admin_task_edit, name='admin_task_edit'),
    path('tasks/admin/stats/', views.admin_task_stats, name='admin_task_stats'),
    path('tasks/admin/stats/export/', views.admin_task_stats_export, name='admin_task_stats_export'),
    path('tasks/admin/export/', views.admin_task_export, name='admin_task_export'),
    path('sla/settings/', views.sla_settings, name='sla_settings'),
    path('workbench/', views.workbench, name='workbench'),
    path('performance/', views.performance_board, name='performance_board'),
    path('performance/export/', views.performance_export, name='performance_export'),
    path('admin/reports/', views.admin_reports, name='admin_reports'),
    path('admin/reports/export/', views.admin_reports_export, name='admin_reports_export'),
    path('advanced/', views.advanced_reporting, name='advanced_reporting'),
    path('my/<int:pk>/edit/', views.report_edit, name='report_edit'),
    path('projects/', views.project_list, name='project_list'),
    path('projects/export/', views.project_export, name='project_export'),
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<int:pk>/', views.project_detail, name='project_detail'),
    path('projects/<int:pk>/edit/', views.project_edit, name='project_edit'),
    path('projects/<int:pk>/delete/', views.project_delete, name='project_delete'),

    path('audit/', views.audit_logs, name='audit_logs'),
    path('audit/export/', views.audit_logs_export, name='audit_logs_export'),
    path('templates/center/', views.template_center, name='template_center'),
    path('templates/api/apply/', views.template_apply_api, name='template_apply_api'),
    path('templates/api/recommend/', views.template_recommend_api, name='template_recommend_api'),
    path('export/jobs/<int:job_id>/', views.export_job_status, name='export_job_status'),
    path('export/jobs/<int:job_id>/download/', views.export_job_download, name='export_job_download'),
    path('prefs/', views_preferences.preference_get_api, name='preference_get_api'),
    path('prefs/save/', views_preferences.preference_save_api, name='preference_save_api'),

    # API
    path('api/projects/<int:pk>/', views.api_project_detail, name='api_project_detail'),
    path('api/tasks/<int:pk>/', views.api_task_detail, name='api_task_detail'),

    # Phase Management
    path('admin/phases/', views.project_phase_config_list, name='project_phase_config_list'),
    path('admin/phases/new/', views.project_phase_config_create, name='project_phase_config_create'),
    path('admin/phases/<int:pk>/edit/', views.project_phase_config_update, name='project_phase_config_update'),
    path('admin/phases/<int:pk>/delete/', views.project_phase_config_delete, name='project_phase_config_delete'),

    # Project Phase Actions
    path('projects/<int:project_id>/update-phase/', views.project_update_phase, name='project_update_phase'),
    path('projects/<int:project_id>/phase-history/', views.project_phase_history, name='project_phase_history'),
    
    # Team Management
    path('teams/', views_teams.teams_list, name='teams'),
    path('teams/<int:user_id>/role/', views_teams.team_member_update_role, name='team_member_update_role'),
    path('teams/<int:user_id>/project/add/', views_teams.team_member_add_project, name='team_member_add_project'),
    path('teams/<int:user_id>/project/<int:project_id>/remove/', views_teams.team_member_remove_project, name='team_member_remove_project'),

    # Project Attachments
    path('projects/<int:project_id>/upload-attachment/', views.project_upload_attachment, name='project_upload_attachment'),
    path('projects/attachments/<int:attachment_id>/delete/', views.project_delete_attachment, name='project_delete_attachment'),

    # Task Attachments
    path('tasks/<int:task_id>/upload-attachment/', views.task_upload_attachment, name='task_upload_attachment'),
    path('tasks/attachments/<int:attachment_id>/delete/', views.task_delete_attachment, name='task_delete_attachment'),
]
