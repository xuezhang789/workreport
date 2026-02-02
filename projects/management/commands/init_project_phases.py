from django.core.management.base import BaseCommand
from projects.models import ProjectPhaseConfig

class Command(BaseCommand):
    help = 'Initialize default project phases'

    def handle(self, *args, **options):
        phases = [
            {'name': '项目启动 / Initiation', 'progress': 0, 'order': 10},
            {'name': '需求分析 / Requirements', 'progress': 10, 'order': 20},
            {'name': '系统设计 / Design', 'progress': 25, 'order': 30},
            {'name': '开发实施 / Implementation', 'progress': 30, 'order': 40},
            {'name': '测试验证 / Testing', 'progress': 75, 'order': 50},
            {'name': '部署上线 / Deployment', 'progress': 90, 'order': 60},
            {'name': '项目结项 / Closing', 'progress': 100, 'order': 70},
        ]

        created_count = 0
        for p in phases:
            phase, created = ProjectPhaseConfig.objects.get_or_create(
                phase_name=p['name'],
                defaults={
                    'progress_percentage': p['progress'],
                    'order_index': p['order'],
                    'is_active': True
                }
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Created phase: {p["name"]}'))
            else:
                # Update existing if needed, or just skip
                phase.progress_percentage = p['progress']
                phase.order_index = p['order']
                phase.save()
                self.stdout.write(f'Updated phase: {p["name"]}')

        self.stdout.write(self.style.SUCCESS(f'Successfully initialized {created_count} new phases.'))
