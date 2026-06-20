from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from cryptography.fernet import Fernet


@register(Tags.security, deploy=True)
def production_operability_checks(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    issues = []
    for key in settings.FIELD_ENCRYPTION_KEYS:
        try:
            Fernet(key.encode('ascii'))
        except (TypeError, ValueError):
            issues.append(Error(
                'FIELD_ENCRYPTION_KEYS contains an invalid Fernet key.',
                id='workreport.E003',
            ))
            break
    if not settings.MFA_REQUIRED_FOR_SUPERUSERS:
        issues.append(Error(
            'Superuser MFA is disabled in production.',
            id='workreport.E001',
        ))
    if not settings.METRICS_TOKEN:
        issues.append(Error(
            'METRICS_TOKEN is required to expose production metrics safely.',
            id='workreport.E002',
        ))
    if not settings.SENTRY_DSN:
        issues.append(Warning(
            'SENTRY_DSN is not configured; production errors will only be available in logs.',
            id='workreport.W001',
        ))
    if settings.ATTACHMENT_STORAGE_CONFIG.get('default') == 'local':
        issues.append(Warning(
            'Attachment storage defaults to local disk; verify persistent volume backups or switch to object storage.',
            id='workreport.W002',
        ))
    if settings.DIRECT_UPLOAD_ENABLED and settings.ATTACHMENT_STORAGE_CONFIG.get('default') == 'local':
        issues.append(Error(
            'DIRECT_UPLOAD_ENABLED requires object storage as the default attachment backend.',
            id='workreport.E004',
        ))
    if 'localhost' in settings.CELERY_BROKER_URL or '127.0.0.1' in settings.CELERY_BROKER_URL:
        issues.append(Warning(
            'CELERY_BROKER_URL points to localhost; verify this is intentional for production.',
            id='workreport.W003',
        ))
    return issues
