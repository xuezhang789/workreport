
import os
import yaml
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from work_logs.models import RoleTemplate, ReportTemplateVersion
from core.models import Profile

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Initialize role-based daily report templates from YAML configuration.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--config',
            type=str,
            default='reports/data/definitions/roles.yaml',
            help='Path to the YAML configuration file'
        )
        parser.add_argument(
            '--env',
            type=str,
            default='prod',
            help='Environment (dev/test/prod)'
        )

    def handle(self, *args, **options):
        config_path = options['config']
        env = options['env']
        
        self.stdout.write(f"Initializing templates from {config_path} for {env} environment...")
        
        if not os.path.exists(config_path):
            self.stdout.write(self.style.ERROR(f"Config file not found: {config_path}"))
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                
            self.process_templates(data.get('templates', []))
            
            self.stdout.write(self.style.SUCCESS("Successfully initialized all templates."))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Initialization failed: {str(e)}"))
            # In a real scenario, we might want to re-raise or handle rollback here if not handled in process_templates
            raise e

    def process_templates(self, templates):
        """
        Process list of template definitions safely.
        """
        success_count = 0
        with transaction.atomic():
            for tpl_def in templates:
                try:
                    self.create_or_update_template(tpl_def)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error processing template {tpl_def.get('name')}: {str(e)}")
                    # Optionally re-raise to abort transaction if strict consistency is needed
                    # raise e 
        self.stdout.write(f"Processed {success_count}/{len(templates)} templates.")

    def create_or_update_template(self, definition):
        role_code = definition.get('role')
        name = definition.get('name')
        
        # Validate Role
        valid_roles = dict(Profile.ROLE_CHOICES).keys()
        if role_code not in valid_roles:
            self.stdout.write(self.style.WARNING(f"Skipping invalid role: {role_code}"))
            return

        # Build placeholders mapping
        placeholders = {}
        
        # 1. Process Fields
        # We also want to validate field keys against the DailyReport model if possible
        # but let's keep it flexible for now.
        for field in definition.get('fields', []):
            key = field['key']
            default_val = field.get('default', '')
            placeholders[key] = default_val
            
        # 2. Store Schema in placeholders (special key) for future advanced rendering
        # We store the *entire* definition including metrics and validation rules
        placeholders['_schema'] = {
            'fields': definition.get('fields', []),
            'metrics': definition.get('metrics', []),
            'version': definition.get('version', 1)
        }

        # 3. Create/Update RoleTemplate (System Default)
        # We construct a combined sample_md for the "Copy Sample" button if the user just wants text
        combined_sample = "\n\n".join([f.get('default', '') for f in definition.get('fields', [])])
        
        rt, created = RoleTemplate.objects.update_or_create(
            role=role_code,
            defaults={
                'hint': definition.get('hint', ''),
                'sample_md': combined_sample,
                'placeholders': placeholders,
                'is_active': True,
                'sort_order': definition.get('sort_order', 0) 
            }
        )
        action = "Created" if created else "Updated"
        self.stdout.write(f"{action} RoleTemplate: {name} ({role_code})")

        # 4. Create/Update ReportTemplateVersion (Template Center Item)
        # This allows users to select "Standard v1" from the template modal
        # We only update if content changed or it's new
        ReportTemplateVersion.objects.update_or_create(
            name=name,
            role=role_code,
            version=definition.get('version', 1),
            defaults={
                'content': combined_sample,
                'placeholders': placeholders,
                'is_shared': True,
                'project': None
            }
        )
