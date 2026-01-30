
from django.test import TestCase
from work_logs.models import RoleTemplate
from core.models import Profile

class RoleTemplateLogicTest(TestCase):
    def test_role_template_update_logic(self):
        role = 'dev'
        
        # 1. Create initial template
        RoleTemplate.objects.create(
            role=role,
            hint='Old Hint',
            placeholders={'key': 'val'},
            sort_order=10
        )
        
        # 2. Simulate View Logic (Update)
        new_hint = 'New Hint'
        new_sample = 'Sample'
        new_placeholders = {'new': 'val'}
        # Simulate empty string from form for integer field
        raw_sort_order = '' 
        
        # This is the logic I plan to add to the view
        try:
            sort_order = int(raw_sort_order) if raw_sort_order.strip() else 0
        except ValueError:
            sort_order = 0
            
        obj, created = RoleTemplate.objects.update_or_create(
            role=role,
            defaults={
                'hint': new_hint,
                'sample_md': new_sample,
                'placeholders': new_placeholders,
                'sort_order': sort_order,
                'is_active': True
            }
        )
        
        self.assertFalse(created)
        self.assertEqual(obj.hint, new_hint)
        self.assertEqual(obj.sort_order, 0)
        self.assertEqual(obj.placeholders, new_placeholders)
