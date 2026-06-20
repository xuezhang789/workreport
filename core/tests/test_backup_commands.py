import hashlib
import json
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class BackupVerificationTests(SimpleTestCase):
    def test_manifest_verification_detects_valid_and_tampered_files(self):
        with tempfile.TemporaryDirectory() as directory:
            backup_dir = Path(directory)
            database = backup_dir / 'database.sqlite3'
            database.write_bytes(b'backup-content')
            manifest = {
                'files': {
                    database.name: {
                        'size': database.stat().st_size,
                        'sha256': hashlib.sha256(database.read_bytes()).hexdigest(),
                    },
                },
            }
            (backup_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

            call_command('verify_backup', backup_dir, verbosity=0)
            database.write_bytes(b'tampered')

            with self.assertRaises(CommandError):
                call_command('verify_backup', backup_dir, verbosity=0)
