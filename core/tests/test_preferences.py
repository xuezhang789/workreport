import json

from django.contrib.auth.models import User
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from core.models import UserPreference
from core.services.preferences import get_request_ui_preferences, normalize_ui_preferences, resolve_page_size


class UserPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pref-user', password='password')
        self.factory = RequestFactory()

    def test_ui_preferences_are_normalized(self):
        normalized = normalize_ui_preferences({
            'page_size': 999,
            'density': 'dense',
            'reduce_motion': 'false',
        })

        self.assertEqual(normalized['page_size'], 20)
        self.assertEqual(normalized['density'], 'comfortable')
        self.assertFalse(normalized['reduce_motion'])

    def test_resolve_page_size_uses_user_preference_when_query_is_absent(self):
        pref = UserPreference.objects.create(
            user=self.user,
            data={'ui': {'page_size': 50, 'density': 'compact'}},
        )

        self.assertEqual(resolve_page_size(self.user, {}, default=20), 50)
        self.assertEqual(resolve_page_size(self.user, {'per_page': '10'}, default=20), 10)

        pref.update_section('ui', {'page_size': 100})
        self.assertEqual(resolve_page_size(self.user, {}, default=20), 100)

    def test_request_page_size_uses_session_without_database(self):
        request = self.factory.get('/tasks/')
        request.user = self.user
        request.session = {
            'ui_preferences': {'page_size': 100, 'density': 'compact', 'reduce_motion': True},
        }

        with self.assertNumQueries(0):
            self.assertEqual(resolve_page_size(request, {}, default=20), 100)
            self.assertEqual(get_request_ui_preferences(request)['density'], 'compact')

        self.assertFalse(UserPreference.objects.filter(user=self.user).exists())

    def test_request_page_size_falls_back_without_creating_preference(self):
        request = self.factory.get('/tasks/')
        request.user = self.user
        request.session = {}

        with self.assertNumQueries(0):
            self.assertEqual(resolve_page_size(request, {}, default=20), 20)

        self.assertFalse(UserPreference.objects.filter(user=self.user).exists())

    def test_login_primes_ui_preferences_session(self):
        UserPreference.objects.create(
            user=self.user,
            data={'ui': {'page_size': 50, 'density': 'compact', 'reduce_motion': True}},
        )

        self.client.login(username='pref-user', password='password')

        self.assertEqual(self.client.session['ui_preferences']['page_size'], 50)
        self.assertEqual(self.client.session['ui_preferences']['density'], 'compact')
        self.assertTrue(self.client.session['ui_preferences']['reduce_motion'])

    def test_preference_api_saves_normalized_ui_section(self):
        self.client.login(username='pref-user', password='password')

        response = self.client.post(reverse('reports:preference_save_api'), {
            'key': 'ui',
            'value': json.dumps({'page_size': 50, 'density': 'compact', 'reduce_motion': True}),
        })

        self.assertEqual(response.status_code, 200)
        pref = self.user.preferences
        self.assertEqual(pref.data['ui']['page_size'], 50)
        self.assertEqual(pref.data['ui']['density'], 'compact')
        self.assertTrue(pref.data['ui']['reduce_motion'])
        self.assertEqual(self.client.session['ui_preferences']['page_size'], 50)

    def test_preference_api_rejects_unknown_sections(self):
        self.client.login(username='pref-user', password='password')

        response = self.client.post(reverse('reports:preference_save_api'), {
            'key': 'unknown',
            'value': '{}',
        })

        self.assertEqual(response.status_code, 400)
