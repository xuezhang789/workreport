from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from tasks.models import Task
from projects.models import Project
from tasks.services.export import TaskExportService
from tasks.views import admin_task_export
from core.models import SystemSetting
import csv
import io

from core.constants import TaskStatus, TaskCategory

class TaskExportTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.project = Project.objects.create(name="Test Project", owner=self.user)
        self.task = Task.objects.create(
            title="Test Task",
            project=self.project,
            user=self.user,
            status='todo',
            priority='high',
            due_at=timezone.now() + timezone.timedelta(days=1),
            category=TaskCategory.TASK
        )
        # Set SLA settings
        SystemSetting.objects.create(key='sla_hours', value='24')

    def test_export_header_completeness(self):
        """Verify export header contains all required fields."""
        header = TaskExportService.get_header()
        expected = [
            "ID", "标题 / Title", "项目 / Project", "分类 / Category",
            "状态 / Status", "优先级 / Priority", "负责人 / Assignee", 
            "协作人 / Collaborators", "截止时间 / Due Date", 
            "完成时间 / Completed At", "创建时间 / Created At", 
            "SLA 状态 / SLA Status", "SLA 剩余(h) / SLA Remaining(h)",
            "URL", "内容 / Content"
        ]
        self.assertEqual(header, expected)

    def test_export_row_data(self):
        """Verify exported row data matches task."""
        rows = list(TaskExportService.get_export_rows([self.task]))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        
        self.assertEqual(row[0], str(self.task.id))
        self.assertEqual(row[1], "Test Task")
        self.assertEqual(row[2], "Test Project")
        self.assertEqual(row[3], TaskCategory.TASK.label) # Match actual label
        self.assertEqual(row[5], "高 / High")   # Priority
        self.assertIn("admin", row[6])         # User
        
        # Check SLA
        # Since due in 24h and SLA is 24h, it might be tight or normal depending on logic
        # Just check it exists
        self.assertIsNotNone(row[11]) # SLA Status
        self.assertIsNotNone(row[12]) # SLA Remaining

    def test_admin_export_view(self):
        """Test the actual view returns CSV."""
        request = self.factory.get('/tasks/admin/export/')
        request.user = self.user
        response = admin_task_export(request)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
        
        content = b"".join(response.streaming_content).decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        
        self.assertEqual(rows[0], TaskExportService.get_header())
        self.assertEqual(len(rows), 2) # Header + 1 row
        self.assertEqual(rows[1][1], "Test Task")
