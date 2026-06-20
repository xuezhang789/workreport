import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = 'Verify every file in a WorkReport backup manifest.'

    def add_arguments(self, parser):
        parser.add_argument('backup_dir', type=Path)

    def handle(self, *args, **options):
        backup_dir = options['backup_dir'].expanduser().resolve()
        manifest_path = backup_dir / 'manifest.json'
        if not manifest_path.is_file():
            raise CommandError('manifest.json is missing')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for filename, metadata in manifest.get('files', {}).items():
            path = backup_dir / filename
            if not path.is_file():
                raise CommandError(f'Missing backup file: {filename}')
            if path.stat().st_size != metadata['size']:
                raise CommandError(f'Size mismatch: {filename}')
            if _sha256(path) != metadata['sha256']:
                raise CommandError(f'Checksum mismatch: {filename}')
        self.stdout.write(self.style.SUCCESS('Backup verification passed.'))
