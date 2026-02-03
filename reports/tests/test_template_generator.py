
from django.test import TestCase
from work_logs.models import RoleTemplate, ReportTemplateVersion
from tasks.models import TaskTemplateVersion
from reports.services.template_generator import TemplateGenerator
from django.core.management import call_command

class TemplateGeneratorTest(TestCase):
    def test_generate_all(self):
        # Clear existing
        RoleTemplate.objects.all().delete()
        ReportTemplateVersion.objects.all().delete()
        TaskTemplateVersion.objects.all().delete()
        
        # Generate
        TemplateGenerator.generate_all()
        
        # Verify RoleTemplates
        self.assertTrue(RoleTemplate.objects.filter(role='dev').exists())
        self.assertTrue(RoleTemplate.objects.filter(role='pm').exists())
        self.assertTrue(RoleTemplate.objects.filter(role='qa').exists())
        
        dev_tpl = RoleTemplate.objects.get(role='dev')
        self.assertIn('API-101', dev_tpl.sample_md)
        self.assertTrue(dev_tpl.placeholders)
        
        # Verify ReportTemplateVersion
        self.assertTrue(ReportTemplateVersion.objects.filter(role='dev', version=1).exists())
        
        # Verify TaskTemplateVersion
        self.assertTrue(TaskTemplateVersion.objects.filter(name__contains='Bug Fix').exists())

    def test_command(self):
        # Clear existing
        RoleTemplate.objects.all().delete()
        
        # Run command
        call_command('init_standard_templates')
        
        self.assertTrue(RoleTemplate.objects.filter(role='mgr').exists())
