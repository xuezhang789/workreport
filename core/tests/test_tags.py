
from django.test import TestCase
from django.template import Template, Context
from django.template.loader import render_to_string
from django.test.client import RequestFactory

class TemplateTagTests(TestCase):
    def test_load_core_tags(self):
        """Test that core_tags library can be loaded and used."""
        try:
            template_string = "{% load core_tags %}{% url_replace param='value' %}"
            template = Template(template_string)
            factory = RequestFactory()
            request = factory.get('/')
            context = Context({'request': request})
            rendered = template.render(context)
            self.assertIn('param=value', rendered)
            print("Successfully loaded and rendered core_tags")
        except Exception as e:
            self.fail(f"Failed to load core_tags: {e}")
