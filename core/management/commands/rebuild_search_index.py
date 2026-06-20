from django.core.management.base import BaseCommand

from core.services.search_index import rebuild_search_index


class Command(BaseCommand):
    help = 'Rebuild the database-backed global search index.'

    def add_arguments(self, parser):
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        counts = rebuild_search_index(batch_size=options['batch_size'])
        self.stdout.write(
            self.style.SUCCESS(
                'Search index rebuilt: '
                f"{counts['projects']} projects, {counts['tasks']} tasks, {counts['reports']} reports"
            )
        )
