
import os
import yaml
from django.test import TestCase
from django.core.management import call_command
from work_logs.models import RoleTemplate, ReportTemplateVersion
from core.models import Profile

class RoleTemplateInitTest(TestCase):
    def setUp(self):
        # Create a temporary config file
        self.config_path = 'reports/data/definitions/test_roles.yaml'
        self.config_data = {
            'templates': [
                {
                    'role': 'dev',
                    'name': 'Test Dev Template',
                    'hint': 'Test Hint',
                    'version': 99,
                    'fields': [
                        {
                            'key': 'today_work',
                            'label': 'Work',
                            'required': True,
                            'type': 'markdown',
                            'default': '### Coding'
                        }
                    ],
                    'metrics': [
                        {'key': 'commits', 'type': 'number'}
                    ]
                }
            ]
        }
        with open(self.config_path, 'w') as f:
            yaml.dump(self.config_data, f)

    def tearDown(self):
        if os.path.exists(self.config_path):
            os.remove(self.config_path)

    def test_init_command(self):
        # Run command
        call_command('init_role_templates', config=self.config_path)
        
        # Verify RoleTemplate
        rt = RoleTemplate.objects.get(role='dev')
        self.assertEqual(rt.hint, 'Test Hint')
        self.assertIn('today_work', rt.placeholders)
        self.assertEqual(rt.placeholders['today_work'], '### Coding')
        self.assertIn('_schema', rt.placeholders)
        self.assertEqual(rt.placeholders['_schema']['version'], 99)
        
        # Verify ReportTemplateVersion
        tv = ReportTemplateVersion.objects.get(role='dev', version=99)
        self.assertEqual(tv.name, 'Test Dev Template')
        self.assertTrue(tv.is_shared)

    def test_idempotency(self):
        # Run twice
        call_command('init_role_templates', config=self.config_path)
        call_command('init_role_templates', config=self.config_path)
        
        # Should still be one record (update_or_create)
        self.assertEqual(RoleTemplate.objects.filter(role='dev').count(), 1)
        self.assertEqual(ReportTemplateVersion.objects.filter(role='dev', version=99).count(), 1)

    def test_invalid_role(self):
        # Add invalid role to config
        self.config_data['templates'].append({
            'role': 'invalid_role',
            'name': 'Bad'
        })
        with open(self.config_path, 'w') as f:
            yaml.dump(self.config_data, f)
            
        call_command('init_role_templates', config=self.config_path)
        
        # Should not create
        self.assertFalse(RoleTemplate.objects.filter(role='invalid_role').exists())
