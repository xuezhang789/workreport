from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from work_logs.models import DailyReport, Attendance
from projects.models import Project
from datetime import date, timedelta
import json

User = get_user_model()

class AttendanceTest(TestCase):
    def setUp(self):
        # Create users
        self.superuser = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.user = User.objects.create_user('employee', 'emp@example.com', 'password')
        
        # Create project
        self.project = Project.objects.create(name="Test Project", owner=self.superuser)
        
        # Client
        self.client = Client()

    def test_attendance_creation_on_report_submission(self):
        """Test that submitting a DailyReport creates an Attendance record."""
        report = DailyReport.objects.create(
            user=self.user,
            date=date(2023, 10, 1),
            status='draft',
            role='dev',
            today_work='Work'
        )
        
        # Check no attendance yet
        self.assertFalse(Attendance.objects.filter(user=self.user, date=report.date).exists())
        
        # Update to submitted
        report.status = 'submitted'
        report.save()
        
        # Check attendance created
        attendance = Attendance.objects.get(user=self.user, date=report.date)
        self.assertEqual(attendance.status, 'present')
        self.assertEqual(attendance.report, report)
        
        # Idempotency: Save again
        report.save()
        self.assertEqual(Attendance.objects.filter(user=self.user, date=report.date).count(), 1)

    def test_attendance_api(self):
        """Test the attendance stats API."""
        # Create some attendance records
        d1 = date(2023, 10, 1)
        d2 = date(2023, 10, 2)
        
        # Day 1: Present (via Report)
        r1 = DailyReport.objects.create(
            user=self.user,
            date=d1,
            status='submitted',
            role='dev',
            today_work='Work'
        )
        
        # Day 2: Leave (Manual)
        Attendance.objects.create(
            user=self.user,
            date=d2,
            status='leave'
        )
        
        # Login as superuser
        self.client.force_login(self.superuser)
        
        # Call API
        response = self.client.get('/reports/api/attendance/stats/', {
            'user_id': self.user.id,
            'month': '2023-10'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        
        self.assertEqual(data['present_days'], 1)
        self.assertEqual(data['leave_days'], 1)
        self.assertEqual(len(data['records']), 2)
        
        # Verify record details
        records = {r['date']: r for r in data['records']}
        self.assertEqual(records[d1.isoformat()]['status'], 'present')
        self.assertEqual(records[d2.isoformat()]['status'], 'leave')

    def test_attendance_api_permission(self):
        """Test that non-superusers cannot access other's attendance."""
        other_user = User.objects.create_user('other', 'other@example.com', 'password')
        self.client.force_login(other_user)
        
        response = self.client.get('/reports/api/attendance/stats/', {
            'user_id': self.user.id,
            'month': '2023-10'
        })
        
        self.assertEqual(response.status_code, 403)
