import json

from django.core.management.base import BaseCommand

from core.services.maintenance import run_runtime_maintenance


class Command(BaseCommand):
    help = 'Run runtime maintenance: stale uploads, expired exports, stuck jobs.'

    def handle(self, *args, **options):
        result = run_runtime_maintenance()
        self.stdout.write(self.style.SUCCESS(json.dumps(result, ensure_ascii=False)))
