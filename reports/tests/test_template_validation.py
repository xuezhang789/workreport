
from django.test import TestCase
from reports.services.template_generator import TemplateGenerator
from reports.data.default_templates import DAILY_REPORT_TEMPLATES

class TemplateValidationTest(TestCase):
    def test_validation_passes(self):
        """Test that the current configuration is valid."""
        errors = TemplateGenerator.validate_config()
        self.assertEqual(errors, [], f"Validation failed with errors: {errors}")

    def test_validation_detects_bad_role(self):
        """Test that invalid roles are detected."""
        original = DAILY_REPORT_TEMPLATES.copy()
        DAILY_REPORT_TEMPLATES['hacker'] = {'role': 'hacker'}
        try:
            errors = TemplateGenerator.validate_config()
            self.assertTrue(any("Invalid role 'hacker'" in e for e in errors))
        finally:
            # Clean up module level variable modification (dangerous but effective for test)
            if 'hacker' in DAILY_REPORT_TEMPLATES:
                del DAILY_REPORT_TEMPLATES['hacker']

    def test_validation_detects_bad_field(self):
        """Test that invalid fields are detected."""
        # Modify the 'dev' template temporarily
        original_placeholders = DAILY_REPORT_TEMPLATES['dev'].get('placeholders', {}).copy()
        DAILY_REPORT_TEMPLATES['dev']['placeholders']['non_existent_field'] = 'Foo'
        try:
            errors = TemplateGenerator.validate_config()
            self.assertTrue(any("Invalid placeholder key 'non_existent_field'" in e for e in errors))
        finally:
            # Restore
            DAILY_REPORT_TEMPLATES['dev']['placeholders'] = original_placeholders
