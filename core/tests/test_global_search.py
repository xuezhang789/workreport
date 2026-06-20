from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class LegacyGlobalSearchTests(TestCase):
    def test_legacy_endpoint_redirects_to_canonical_search(self):
        user = User.objects.create_user('searcher', password='password')
        self.client.force_login(user)

        response = self.client.get(reverse('core:global_search'), {'q': 'daily plan'})

        self.assertRedirects(
            response,
            reverse('reports:global_search') + '?q=daily+plan',
            fetch_redirect_response=False,
        )
