from io import StringIO

from django.core.management import call_command
from django.test import SimpleTestCase


class ApiContractTests(SimpleTestCase):
    def test_openapi_contract_routes_are_valid(self):
        output = StringIO()

        call_command('validate_api_contract', stdout=output)

        self.assertIn('OpenAPI contract validated', output.getvalue())
