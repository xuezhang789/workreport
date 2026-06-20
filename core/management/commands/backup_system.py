import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Command(BaseCommand):
    help = 'Create a checksummed native database backup and optional media archive.'

    def add_arguments(self, parser):
        parser.add_argument('--output-dir', type=Path, default=settings.BACKUP_ROOT)
        parser.add_argument('--include-media', action='store_true')
        parser.add_argument('--retention-days', type=int, default=30)

    def handle(self, *args, **options):
        output_root = options['output_dir'].expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        timestamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
        target = output_root / f'workreport-{timestamp}'

        with tempfile.TemporaryDirectory(prefix='.workreport-backup-', dir=output_root) as temp_dir:
            temp_target = Path(temp_dir)
            database_file = self._backup_database(temp_target)
            files = [database_file]
            if options['include_media'] and Path(settings.MEDIA_ROOT).exists():
                media_file = temp_target / 'media.tar.gz'
                with tarfile.open(media_file, 'w:gz') as archive:
                    archive.add(settings.MEDIA_ROOT, arcname='media')
                files.append(media_file)

            manifest = {
                'format_version': 1,
                'created_at': timezone.now().isoformat(),
                'database_vendor': connections['default'].vendor,
                'files': {
                    path.name: {
                        'size': path.stat().st_size,
                        'sha256': _sha256(path),
                    }
                    for path in files
                },
            }
            (temp_target / 'manifest.json').write_text(
                json.dumps(manifest, ensure_ascii=True, indent=2),
                encoding='utf-8',
            )
            shutil.move(str(temp_target), target)

        self._prune(output_root, options['retention_days'])
        self.stdout.write(self.style.SUCCESS(str(target)))

    def _backup_database(self, target):
        connection = connections['default']
        config = connection.settings_dict
        connection.close()

        if connection.vendor == 'sqlite':
            source_path = Path(config['NAME']).resolve()
            destination = target / 'database.sqlite3'
            with sqlite3.connect(source_path) as source, sqlite3.connect(destination) as backup:
                source.backup(backup)
            return destination

        if connection.vendor == 'postgresql':
            destination = target / 'database.dump'
            env = os.environ.copy()
            env['PGPASSWORD'] = str(config.get('PASSWORD') or '')
            command = [
                'pg_dump', '--format=custom', '--no-owner',
                '--file', str(destination), '--dbname', str(config['NAME']),
                '--username', str(config['USER']), '--host', str(config['HOST']),
            ]
            if config.get('PORT'):
                command.extend(['--port', str(config['PORT'])])
            self._run(command, env=env)
            return destination

        if connection.vendor == 'mysql':
            destination = target / 'database.sql'
            env = os.environ.copy()
            env['MYSQL_PWD'] = str(config.get('PASSWORD') or '')
            command = [
                'mysqldump', '--single-transaction', '--routines', '--triggers',
                '--user', str(config['USER']), '--host', str(config['HOST']),
            ]
            if config.get('PORT'):
                command.extend(['--port', str(config['PORT'])])
            command.append(str(config['NAME']))
            with destination.open('wb') as output:
                self._run(command, env=env, stdout=output)
            return destination

        raise CommandError(f'Unsupported database vendor: {connection.vendor}')

    def _run(self, command, **kwargs):
        try:
            subprocess.run(command, check=True, stderr=subprocess.PIPE, **kwargs)
        except FileNotFoundError as exc:
            raise CommandError(f'Required backup tool is missing: {command[0]}') from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b'').decode(errors='replace').strip()
            raise CommandError(f"Backup command failed: {detail}") from exc

    def _prune(self, output_root, retention_days):
        if retention_days <= 0:
            return
        cutoff = timezone.now() - timedelta(days=retention_days)
        for path in output_root.glob('workreport-*'):
            if path.is_dir() and datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.get_current_timezone(),
            ) < cutoff:
                shutil.rmtree(path)
