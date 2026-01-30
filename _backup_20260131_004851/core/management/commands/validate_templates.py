from django.core.management.base import BaseCommand
from django.template.loader import get_template
from django.template import TemplateDoesNotExist, TemplateSyntaxError
import os

class Command(BaseCommand):
    help = 'Validate all templates for syntax errors'

    def handle(self, *args, **options):
        template_dir = 'templates'
        errors = []
        checked = 0

        for root, dirs, files in os.walk(template_dir):
            for file in files:
                if file.endswith('.html'):
                    path = os.path.join(root, file)
                    # Rel path for get_template
                    rel_path = os.path.relpath(path, template_dir)
                    checked += 1
                    try:
                        get_template(rel_path)
                    except TemplateSyntaxError as e:
                        errors.append(f"Syntax Error in {rel_path}: {e}")
                    except TemplateDoesNotExist as e:
                         # This usually shouldn't happen if we iterate existing files, 
                         # but maybe if an include is missing
                        errors.append(f"Template Includes Missing in {rel_path}: {e}")
                    except Exception as e:
                        errors.append(f"Error in {rel_path}: {e}")

        self.stdout.write(f"Checked {checked} templates.")
        if errors:
            self.stdout.write(self.style.ERROR(f"Found {len(errors)} errors:"))
            for err in errors:
                self.stdout.write(self.style.ERROR(err))
        else:
            self.stdout.write(self.style.SUCCESS("All templates passed syntax validation."))
