from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from reports import views as report_views
from projects import views_api as project_api_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/users/<int:user_id>/responsible-projects', project_api_views.get_user_responsible_projects),
    path('core/', include('core.urls')), # Allow /core/api/upload/...
    path('accounts/', include('core.urls')),
    path('projects/', include('projects.urls')),
    path('tasks/', include('tasks.urls')),
    path('reports/', include('reports.urls')),
    path('', RedirectView.as_view(pattern_name='reports:workbench', permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
