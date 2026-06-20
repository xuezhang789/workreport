from django.test import TestCase, override_settings


class ObservabilityEndpointTests(TestCase):
    def test_request_id_is_preserved_when_valid(self):
        response = self.client.get('/healthz', HTTP_X_REQUEST_ID='trace-123')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Request-ID'], 'trace-123')

    def test_invalid_request_id_is_replaced(self):
        response = self.client.get('/healthz', HTTP_X_REQUEST_ID='invalid request id')

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response['X-Request-ID'], 'invalid request id')
        self.assertEqual(len(response['X-Request-ID']), 32)

    def test_readiness_checks_database_and_cache(self):
        response = self.client.get('/readyz')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['checks'], {'database': 'ok', 'cache': 'ok'})

    @override_settings(DEBUG=False, METRICS_TOKEN='metrics-secret')
    def test_metrics_are_hidden_without_token(self):
        self.assertEqual(self.client.get('/metrics').status_code, 404)
        response = self.client.get('/metrics', HTTP_AUTHORIZATION='Bearer metrics-secret')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'workreport_http_requests_total', response.content)
