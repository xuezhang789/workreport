from django.core.management.base import BaseCommand
from work_logs.models import DailyReport, Attendance
from django.db import transaction

class Command(BaseCommand):
    help = '从现有日报回填考勤记录'

    def handle(self, *args, **options):
        self.stdout.write("Starting backfill...")
        
        # 获取所有已提交但没有考勤记录的日报
        reports = DailyReport.objects.filter(status='submitted').exclude(attendance_record__isnull=False)
        total = reports.count()
        self.stdout.write(f"Found {total} reports to process.")
        
        batch_size = 1000
        processed = 0
        
        # 使用迭代器处理大数据集
        for report in reports.iterator(chunk_size=batch_size):
            Attendance.objects.get_or_create(
                user=report.user,
                date=report.date,
                defaults={
                    'status': 'present',
                    'report': report
                }
            )
            processed += 1
            if processed % batch_size == 0:
                self.stdout.write(f"Processed {processed}/{total}")
        
        self.stdout.write(self.style.SUCCESS(f"Successfully backfilled {processed} attendance records."))
