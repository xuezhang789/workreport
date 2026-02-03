
from django.core.management.base import BaseCommand
from reports.services.template_generator import TemplateGenerator

class Command(BaseCommand):
    help = 'Validate the structure and fields of standard daily report templates.'

    def handle(self, *args, **options):
        self.stdout.write('Validating standard templates...')
        
        errors = TemplateGenerator.validate_config()
        
        if errors:
            self.stdout.write(self.style.ERROR(f"Found {len(errors)} errors:"))
            for err in errors:
                self.stdout.write(self.style.ERROR(f"- {err}"))
            exit(1)
        else:
            self.stdout.write(self.style.SUCCESS('All standard templates are valid.'))
