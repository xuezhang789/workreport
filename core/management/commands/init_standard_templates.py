
from django.core.management.base import BaseCommand
from reports.services.template_generator import TemplateGenerator

class Command(BaseCommand):
    help = 'Initialize standard templates for Daily Reports and Tasks using TemplateGenerator service.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting standard template initialization...'))

        try:
            TemplateGenerator.generate_all()
            self.stdout.write(self.style.SUCCESS('Successfully initialized all standard templates.'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error initializing templates: {e}'))
            raise e
