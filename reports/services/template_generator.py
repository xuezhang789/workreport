
import logging
from django.db import transaction
from work_logs.models import RoleTemplate, ReportTemplateVersion
from tasks.models import TaskTemplateVersion
from reports.data.default_templates import DAILY_REPORT_TEMPLATES, TASK_TEMPLATES

logger = logging.getLogger(__name__)

class TemplateGenerator:
    """
    Service to generate and manage standard templates.
    """

    @classmethod
    def generate_all(cls):
        """
        Generate all standard templates (Report and Task).
        """
        with transaction.atomic():
            cls.generate_daily_report_templates()
            cls.generate_task_templates()

    @classmethod
    def generate_daily_report_templates(cls):
        """
        Initialize or update standard daily report templates.
        """
        logger.info("Generating Daily Report Templates...")
        
        for key, t in DAILY_REPORT_TEMPLATES.items():
            # 1. Update RoleTemplate (Form Hints)
            role_tpl, created = RoleTemplate.objects.update_or_create(
                role=t['role'],
                defaults={
                    'hint': t['hint'],
                    'sample_md': t['sample_md'],
                    'placeholders': t.get('placeholders', {}),
                    'is_active': True,
                    'sort_order': 0
                }
            )
            action = "Created" if created else "Updated"
            logger.info(f"{action} RoleTemplate for {t['role']}")

            # 2. Update ReportTemplateVersion (Template Center)
            # We use update_or_create on (name, role, version=1) to ensure we have at least one standard version.
            # If user wants to fork, they create new versions.
            ReportTemplateVersion.objects.update_or_create(
                name=t['name'],
                role=t['role'],
                version=1,
                defaults={
                    'content': t['sample_md'],
                    'placeholders': t.get('placeholders', {}),
                    'is_shared': True,
                    'project': None, # Global
                    'created_by': None # System
                }
            )

    @classmethod
    def generate_task_templates(cls):
        """
        Initialize or update standard task templates.
        """
        logger.info("Generating Task Templates...")
        
        for t in TASK_TEMPLATES:
            TaskTemplateVersion.objects.update_or_create(
                name=t['name'],
                version=1,
                defaults={
                    'title': t['title'],
                    'content': t['content'],
                    'is_shared': True,
                    'project': None,
                    'role': None
                }
            )
            logger.info(f"Updated Task Template: {t['name']}")
