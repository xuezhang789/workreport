import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


CONFIRMATION = 'RESTORE-WORKREPORT'


class Command(BaseCommand):
    help = 'Restore a verified WorkReport native database backup and optional media archive.'

    def add_arguments(self, parser):
        parser.add_argument('backup_dir', type=Path)
        parser.add_argument('--confirm', required=True)
        parser.add_argument('--restore-media', action='store_true')

    def handle(self, *args, **options):
        if options['confirm'] != CONFIRMATION:
            raise CommandError(f'Pass --confirm={CONFIRMATION} to acknowledge destructive restore.')

        backup_dir = options['backup_dir'].expanduser().resolve()
        call_command('verify_backup', backup_dir)
        manifest = json.loads((backup_dir / 'manifest.json').read_text(encoding='utf-8'))
        vendor = connections['default'].vendor
        if manifest.get('database_vendor') != vendor:
            raise CommandError('Backup database vendor does not match the configured database.')

        self._restore_database(backup_dir, vendor)
        if options['restore_media'] and (backup_dir / 'media.tar.gz').is_file():
            self._restore_media(backup_dir / 'media.tar.gz')
        self.stdout.write(self.style.SUCCESS('Restore completed. Run application smoke tests now.'))

    def _restore_database(self, backup_dir, vendor):
        connection = connections['default']
        config = connection.settings_dict
        connections.close_all()

        if vendor == 'sqlite':
            source = backup_dir / 'database.sqlite3'
            destination = Path(config['NAME']).resolve()
            temp_destination = destination.with_suffix('.restore.tmp')
            temp_destination.unlink(missing_ok=True)
            with sqlite3.connect(source) as backup, sqlite3.connect(temp_destination) as restored:
                backup.backup(restored)
            temp_destination.replace(destination)
            return

        env = os.environ.copy()
        if vendor == 'postgresql':
            env['PGPASSWORD'] = str(config.get('PASSWORD') or '')
            command = [
                'pg_restore', '--clean', '--if-exists', '--no-owner',
                '--dbname', str(config['NAME']), '--username', str(config['USER']),
                '--host', str(config['HOST']),
            ]
            if config.get('PORT'):
                command.extend(['--port', str(config['PORT'])])
            command.append(str(backup_dir / 'database.dump'))
            self._run(command, env=env)
            return

        if vendor == 'mysql':
            env['MYSQL_PWD'] = str(config.get('PASSWORD') or '')
            command = ['mysql', '--user', str(config['USER']), '--host', str(config['HOST'])]
            if config.get('PORT'):
                command.extend(['--port', str(config['PORT'])])
            command.append(str(config['NAME']))
            with (backup_dir / 'database.sql').open('rb') as source:
                self._run(command, env=env, stdin=source)
            return

        raise CommandError(f'Unsupported database vendor: {vendor}')

    def _restore_media(self, archive_path):
        media_root = Path(settings.MEDIA_ROOT).resolve()
        parent = media_root.parent
        temp_root = parent / f'.{media_root.name}.restore'
        if temp_root.exists():
            shutil.rmtree(temp_root)
        temp_root.mkdir(parents=True)
        with tarfile.open(archive_path, 'r:gz') as archive:
            archive.extractall(temp_root, filter='data')
        extracted = temp_root / 'media'
        if media_root.exists():
            shutil.rmtree(media_root)
        shutil.move(str(extracted), media_root)
        shutil.rmtree(temp_root)

    def _run(self, command, **kwargs):
        try:
            subprocess.run(command, check=True, stderr=subprocess.PIPE, **kwargs)
        except FileNotFoundError as exc:
            raise CommandError(f'Required restore tool is missing: {command[0]}') from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b'').decode(errors='replace').strip()
            raise CommandError(f"Restore command failed: {detail}") from exc
