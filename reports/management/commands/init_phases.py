from django.core.management.base import BaseCommand
from reports.models import ProjectPhaseConfig

class Command(BaseCommand):
    help = 'Initialize default project phases'

    def handle(self, *args, **kwargs):
        phases = [
            ('项目立项', 10, 1),
            ('需求分析', 20, 2),
            ('需求评审', 30, 3),
            ('设计评审', 40, 4),
            ('开发实施', 60, 5),
            ('质量测试', 80, 6),
            ('交付验收', 90, 7),
            ('上线发布', 100, 8),
        ]

        for name, percentage, order in phases:
            obj, created = ProjectPhaseConfig.objects.get_or_create(
                phase_name=name,
                defaults={
                    'progress_percentage': percentage,
                    'order_index': order,
                    'is_active': True
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created phase: {name}'))
            else:
                self.stdout.write(f'Phase already exists: {name}')
