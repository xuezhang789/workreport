from django.urls import path
from . import views
from . import views_export
from . import views_api

app_name = 'projects'

urlpatterns = [
    # Project List & Management
    path('', views.project_list, name='project_list'),
    path('export/', views.project_export, name='project_export'),
    path('new/', views.project_create, name='project_create'),
    path('<int:pk>/', views.project_detail, name='project_detail'),
    path('<int:pk>/edit/', views.project_edit, name='project_edit'),
    path('<int:pk>/delete/', views.project_delete, name='project_delete'),

    # Project Phase Actions
    path('<int:project_id>/update-phase/', views.project_update_phase, name='project_update_phase'),
    path('<int:project_id>/history/', views.project_history, name='project_history'),
    path('<int:project_id>/history/export/', views_export.project_history_export, name='project_history_export'),

    # Attachments
    path('<int:project_id>/upload-attachment/', views.project_upload_attachment, name='project_upload_attachment'),
    path('attachments/<int:attachment_id>/delete/', views.project_delete_attachment, name='project_delete_attachment'),

    # Phase Configuration (Admin)
    path('phases/', views.project_phase_config_list, name='project_phase_config_list'),
    path('phases/new/', views.project_phase_config_create, name='project_phase_config_create'),
    path('phases/<int:pk>/edit/', views.project_phase_config_update, name='project_phase_config_update'),
    path('phases/<int:pk>/delete/', views.project_phase_config_delete, name='project_phase_config_delete'),

    # API
    path('api/search/', views.project_search_api, name='project_search_api'),
    path('api/<int:pk>/', views.api_project_detail, name='api_project_detail'),
    
    # New Management APIs
    path('api/<int:project_id>/manage-members/', views_api.project_manage_members_api, name='project_manage_members_api'),
    path('api/<int:project_id>/users/', views_api.project_users_api, name='project_users_api'),
]
