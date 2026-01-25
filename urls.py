from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from reports import views as report_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(
        template_name='registration/login.html'
    ), name='login'),
    path('accounts/register/', report_views.register, name='register'),
    path('accounts/settings/', report_views.account_settings, name='account_settings'),
    path('accounts/api/username-check/', report_views.username_check_api, name='username_check_api'),
    path('accounts/api/email-code/', report_views.send_email_code_api, name='send_email_code_api'),
    path('accounts/logout/', report_views.logout_view, name='logout'),
    path('reports/', include('reports.urls')),
    path('', RedirectView.as_view(pattern_name='reports:workbench', permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
