from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from core.api import upload_api

app_name = 'core'

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('register/', views.register, name='register'),
    path('settings/', views.account_settings, name='account_settings'),
    path('api/username-check/', views.username_check_api, name='username_check_api'),
    path('api/email-code/', views.send_email_code_api, name='send_email_code_api'),
    path('api/users/', views.user_search_api, name='user_search_api'),
    path('logout/', views.logout_view, name='logout'),
    path('export/jobs/<int:job_id>/', views.export_job_status, name='export_job_status'),
    path('export/jobs/<int:job_id>/download/', views.export_job_download, name='export_job_download'),
    
    # Upload API
    path('api/upload/init/', upload_api.upload_init, name='upload_init'),
    path('api/upload/chunk/', upload_api.upload_chunk, name='upload_chunk'),
    path('api/upload/complete/', upload_api.upload_complete, name='upload_complete'),
    path('api/upload/avatar/complete/', upload_api.upload_avatar_complete, name='upload_avatar_complete'),
]
