from django.db import migrations, models


CONTENT_FIELDS = (
    'today_work',
    'progress_issues',
    'tomorrow_plan',
    'testing_scope',
    'testing_progress',
    'bug_summary',
    'testing_tomorrow',
    'product_today',
    'product_coordination',
    'product_tomorrow',
    'ui_today',
    'ui_feedback',
    'ui_tomorrow',
    'ops_today',
    'ops_monitoring',
    'ops_tomorrow',
    'mgr_progress',
    'mgr_risks',
    'mgr_tomorrow',
)
CURRENT_SCHEMA_VERSION = 2


def _normalize_known_value(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_content(content):
    if not isinstance(content, dict):
        return {}

    allowed_root_keys = set(CONTENT_FIELDS) | {'_legacy_project', '_extra'}
    normalized = {}
    extra = {}

    for key, value in content.items():
        if key == '_extra':
            if isinstance(value, dict):
                for extra_key, extra_value in value.items():
                    if extra_value not in (None, ''):
                        extra[extra_key] = extra_value
            elif value not in (None, ''):
                extra['value'] = value
            continue

        if key in allowed_root_keys:
            normalized_value = _normalize_known_value(value)
            if normalized_value:
                normalized[key] = normalized_value
        elif value not in (None, ''):
            extra[key] = value

    if extra:
        normalized['_extra'] = extra
    return normalized


def normalize_existing_reports(apps, schema_editor):
    DailyReport = apps.get_model('work_logs', 'DailyReport')
    pending = []
    for report in DailyReport.objects.only('id', 'content', 'content_schema_version').iterator():
        normalized = _normalize_content(report.content)
        if report.content != normalized or report.content_schema_version != CURRENT_SCHEMA_VERSION:
            report.content = normalized
            report.content_schema_version = CURRENT_SCHEMA_VERSION
            pending.append(report)
        if len(pending) >= 500:
            DailyReport.objects.bulk_update(pending, ['content', 'content_schema_version'])
            pending.clear()
    if pending:
        DailyReport.objects.bulk_update(pending, ['content', 'content_schema_version'])


class Migration(migrations.Migration):

    dependencies = [
        ('work_logs', '0004_remove_dailyreport_bug_summary_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailyreport',
            name='content_schema_version',
            field=models.PositiveSmallIntegerField(default=2, verbose_name='内容 Schema 版本'),
        ),
        migrations.RunPython(normalize_existing_reports, migrations.RunPython.noop),
    ]
