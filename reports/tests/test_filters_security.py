from django.template import Context, Template
from django.test import TestCase


class ReportsFilterSecurityTests(TestCase):
    def test_pretty_json_escapes_embedded_html(self):
        template = Template('{% load reports_filters %}{{ value|pretty_json }}')
        rendered = template.render(Context({
            'value': {'note': '<script>alert("x")</script>'},
        }))

        self.assertIn('&lt;script&gt;alert(', rendered)
        self.assertIn('\\&quot;x\\&quot;', rendered)
        self.assertNotIn('<script>', rendered)
