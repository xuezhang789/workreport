import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class RuntimeConfigurationTests(SimpleTestCase):
    def test_canonical_asgi_entrypoint_is_configured(self):
        self.assertEqual(settings.ASGI_APPLICATION, 'workreport.asgi.application')

    def test_tests_use_in_memory_channel_layer(self):
        self.assertEqual(
            settings.CHANNEL_LAYERS['default']['BACKEND'],
            'channels.layers.InMemoryChannelLayer',
        )

    def test_tests_use_local_memory_cache(self):
        self.assertEqual(
            settings.CACHES['default']['BACKEND'],
            'django.core.cache.backends.locmem.LocMemCache',
        )

    def test_production_rejects_implicit_sqlite_database(self):
        result = self._import_settings_in_production()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Production requires an explicit PostgreSQL/MySQL database', result.stderr)

    def test_controlled_deploy_check_can_explicitly_allow_sqlite(self):
        result = self._import_settings_in_production(DJANGO_ALLOW_SQLITE_IN_PRODUCTION='True')

        self.assertEqual(result.returncode, 0, result.stderr)

    @staticmethod
    def _import_settings_in_production(**overrides):
        environment = {
            'PATH': os.environ.get('PATH', ''),
            'PYTHONPATH': str(settings.BASE_DIR),
            'DJANGO_SECRET_KEY': 'production-test-secret-key-with-sufficient-length',
            'DJANGO_DEBUG': 'False',
            'DJANGO_TEST_MODE': '0',
            'FIELD_ENCRYPTION_KEYS': 'j3On4pp-WU-C4aaC5PUMQtNOgSSI20r_dgzYr4gDJIo=',
            'CHANNEL_LAYER_BACKEND': 'memory',
            'CACHE_BACKEND': 'locmem',
        }
        environment.update(overrides)
        return subprocess.run(
            [sys.executable, '-c', 'import settings'],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
