from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = '核心系统'

    def ready(self):
        import core.checks  # noqa: F401
        import core.signals  # noqa: F401
