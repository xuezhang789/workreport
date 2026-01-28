from django.urls import path
from . import views

app_name = 'tasks'

urlpatterns = [
    # Task List & Management
    path('', views.task_list, name='task_list'),
    path('bulk/', views.task_bulk_action, name='task_bulk_action'),
    path('export/', views.task_export, name='task_export'),
    path('export/selected/', views.task_export_selected, name='task_export_selected'),
    path('export/jobs/<int:job_id>/', views.export_job_status, name='export_job_status'),
    path('export/jobs/<int:job_id>/download/', views.export_job_download, name='export_job_download'),
    
    path('<int:pk>/complete/', views.task_complete, name='task_complete'),
    path('<int:pk>/view/', views.task_view, name='task_view'),
    path('<int:pk>/history/', views.task_history, name='task_history'),
    
    # Task Attachments
    path('<int:task_id>/upload-attachment/', views.task_upload_attachment, name='task_upload_attachment'),
    path('attachments/<int:attachment_id>/delete/', views.task_delete_attachment, name='task_delete_attachment'),

    # Admin Task Management
    path('admin/', views.admin_task_list, name='admin_task_list'),
    path('admin/bulk/', views.admin_task_bulk_action, name='admin_task_bulk_action'),
    path('admin/new/', views.admin_task_create, name='admin_task_create'),
    path('<int:pk>/edit/', views.admin_task_edit, name='admin_task_edit'),
    path('admin/stats/', views.admin_task_stats, name='admin_task_stats'),
    path('admin/stats/export/', views.admin_task_stats_export, name='admin_task_stats_export'),
    path('admin/export/', views.admin_task_export, name='admin_task_export'),
    
    # SLA Settings
    path('sla/settings/', views.sla_settings, name='sla_settings'),

    # API
    path('api/<int:pk>/', views.api_task_detail, name='api_task_detail'),
]
