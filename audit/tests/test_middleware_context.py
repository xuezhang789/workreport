from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, override_settings

from audit.middleware import (
    AuditMiddleware,
    get_current_ip,
    get_current_request,
    get_current_user,
)


class AuditMiddlewareContextTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_context_is_available_during_request_and_cleaned_afterwards(self):
        request = self.factory.get('/', REMOTE_ADDR='127.0.0.1')
        request.user = User(username='operator')

        def get_response(current_request):
            self.assertIs(get_current_request(), current_request)
            self.assertIs(get_current_user(), current_request.user)
            self.assertEqual(get_current_ip(), '127.0.0.1')
            return object()

        AuditMiddleware(get_response)(request)

        self.assertIsNone(get_current_request())
        self.assertIsNone(get_current_user())
        self.assertIsNone(get_current_ip())

    def test_context_is_cleaned_when_view_raises(self):
        request = self.factory.get('/', REMOTE_ADDR='127.0.0.1')
        request.user = User(username='operator')

        def get_response(_request):
            raise RuntimeError('view failed')

        with self.assertRaises(RuntimeError):
            AuditMiddleware(get_response)(request)

        self.assertIsNone(get_current_request())
        self.assertIsNone(get_current_user())
        self.assertIsNone(get_current_ip())

    @override_settings(TRUST_PROXY_HEADERS=False)
    def test_untrusted_forwarded_ip_is_ignored(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='10.0.0.8',
            HTTP_X_FORWARDED_FOR='203.0.113.99',
        )
        middleware = AuditMiddleware(lambda _request: None)
        self.assertEqual(middleware._get_client_ip(request), '10.0.0.8')

    @override_settings(TRUST_PROXY_HEADERS=True)
    def test_trusted_proxy_uses_x_real_ip(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_REAL_IP='203.0.113.10',
        )
        middleware = AuditMiddleware(lambda _request: None)
        self.assertEqual(middleware._get_client_ip(request), '203.0.113.10')
