import json
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache

from reports.models import Project, DailyReport, Task, SystemSetting, ReportTemplateVersion
from reports import views as report_views
from reports.services.sla import calculate_sla_info, _ensure_sla_timer


class CacheAndTemplateTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='pass', is_staff=True, is_superuser=True)
        self.client.login(username='admin', password='pass')
        self.project = Project.objects.create(name='P1', code='P1', owner=self.admin)

    def test_sla_thresholds_configurable(self):
        resp = self.client.post(reverse('reports:sla_settings'), {
            'sla_hours': '24',
            'sla_amber': '6',
            'sla_red': '2',
        })
        self.assertEqual(resp.status_code, 200)
        cfg = SystemSetting.objects.get(key='sla_thresholds')
        data = json.loads(cfg.value)
        self.assertEqual(data['amber'], 6)
        self.assertEqual(data['red'], 2)

    def test_template_apply_fallback(self):
        # 创建仅角色的全局模板
        ReportTemplateVersion.objects.create(
            name='RoleOnly',
            role='dev',
            project=None,
            content='global dev content',
            placeholders={'today_work': 'fallback content'},
            is_shared=True,
            version=1,
            created_by=self.admin,
        )
        url = reverse('reports:template_apply_api')
        resp = self.client.get(url, {'type': 'report', 'role': 'dev', 'project': self.project.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('fallback', data)
        self.assertTrue(data['fallback'])
        self.assertEqual(data['placeholders']['today_work'], 'fallback content')

    def test_cache_invalidation_on_task_save(self):
        Task.objects.create(title='t1', user=self.admin, project=self.project)
        # 写入一个假的缓存键，再触发 save 来刷新
        cache.set('performance_stats_v1_None_None', {'dummy': True})
        t = Task.objects.first()
        t.title = 't1-updated'
        t.save()
        self.assertIsNone(cache.get('performance_stats_v1_None_None'))

    def test_admin_forbidden_uses_template(self):
        # 非管理员访问管理员页应 403 并渲染友好页
        user = User.objects.create_user(username='u1', password='pass', is_staff=False)
        c = Client()
        c.login(username='u1', password='pass')
        resp = c.get(reverse('reports:performance_board'))
        self.assertEqual(resp.status_code, 403)
        self.assertIn(b'Access denied', resp.content)

    def test_stats_cache_key_invalidated_on_report(self):
        from django.core.cache import cache
        today = timezone.localdate()
        cache_key = f"stats_metrics_v1_{today}_None_"
        cache.set(cache_key, {'dummy': True})
        DailyReport.objects.create(user=self.admin, date=today, role='dev', status='submitted')
        self.assertIsNone(cache.get(cache_key))

    def test_export_limit_message(self):
        original = report_views.MAX_EXPORT_ROWS
        report_views.MAX_EXPORT_ROWS = 1
        try:
            # 创建两个任务，导出触发限额
            Task.objects.create(title='t1', user=self.admin, project=self.project)
            Task.objects.create(title='t2', user=self.admin, project=self.project)
            resp = self.client.get(reverse('reports:task_export'))
            self.assertEqual(resp.status_code, 400)
            content = resp.content.decode()
            self.assertIn("数据量过大", content)
            self.assertIn("Data too large", content)
        finally:
            report_views.MAX_EXPORT_ROWS = original

    def test_admin_reports_export_limit(self):
        original = report_views.MAX_EXPORT_ROWS
        report_views.MAX_EXPORT_ROWS = 1
        try:
            today = timezone.localdate()
            DailyReport.objects.create(user=self.admin, date=today, role='dev', status='submitted')
            DailyReport.objects.create(user=self.admin, date=today, role='qa', status='submitted')
            resp = self.client.get(reverse('reports:admin_reports_export'), {
                'start_date': today,
                'end_date': today,
                'username': self.admin.username,
            })
            self.assertEqual(resp.status_code, 400)
            content = resp.content.decode()
            self.assertIn("数据量过大", content)
            self.assertIn("Data too large", content)
        finally:
            report_views.MAX_EXPORT_ROWS = original

    def test_admin_task_export_limit(self):
        original = report_views.MAX_EXPORT_ROWS
        report_views.MAX_EXPORT_ROWS = 1
        try:
            Task.objects.create(title='t1', user=self.admin, project=self.project)
            Task.objects.create(title='t2', user=self.admin, project=self.project)
            resp = self.client.get(reverse('reports:admin_task_export'))
            self.assertEqual(resp.status_code, 400)
            content = resp.content.decode()
            self.assertIn("数据量过大", content)
            self.assertIn("Data too large", content)
        finally:
            report_views.MAX_EXPORT_ROWS = original

    def test_template_center_pagination(self):
        # 创建超过一页的模板
        for i in range(12):
            ReportTemplateVersion.objects.create(
                name=f'T{i}',
                role='dev',
                project=None,
                content='c',
                is_shared=True,
                version=i + 1,
                created_by=self.admin,
            )
        resp = self.client.get(reverse('reports:template_center'))
        page = resp.context['report_templates']
        self.assertTrue(page.paginator.num_pages >= 2)
        # 排序参数保持
        resp_sort = self.client.get(reverse('reports:template_center'), {'sort': 'updated'})
        self.assertEqual(resp_sort.context['sort'], 'updated')

    def test_post_only_endpoint_forbidden(self):
        resp = self.client.get(reverse('reports:task_bulk_action'))
        self.assertEqual(resp.status_code, 403)
        self.assertIn("POST only".lower(), resp.content.decode().lower())

    def test_sla_threshold_display_in_task_list(self):
        # 创建即将超时的任务以触发 SLA 提示
        t = Task.objects.create(title='t1', user=self.admin, project=self.project)
        Task.objects.filter(id=t.id).update(created_at=timezone.now() - timedelta(hours=23))
        resp = self.client.get(reverse('reports:task_list'))
        self.assertContains(resp, "SLA 阈值")

    def test_sla_threshold_display_in_performance_board(self):
        resp = self.client.get(reverse('reports:performance_board'))
        self.assertContains(resp, "SLA 阈值")

    def test_cache_invalidated_on_report_m2m_change(self):
        from django.core.cache import cache
        today = timezone.localdate()
        report = DailyReport.objects.create(user=self.admin, date=today, role='dev', status='submitted')
        cache_key = f"stats_metrics_v1_{today}_None_"
        cache.set(cache_key, {'dummy': True})
        report.projects.add(self.project)  # 触发 m2m_changed 信号
        self.assertIsNone(cache.get(cache_key))

    def test_sla_uses_due_date_when_present(self):
        # 设置未来 4 小时的截止时间，预期进入 Amber 区间（默认为 6/2 小时阈值）
        due_at = timezone.now() + timedelta(hours=4)
        task = Task.objects.create(title='t1', user=self.admin, project=self.project, due_at=due_at)
        info = calculate_sla_info(task)
        self.assertEqual(info['status'], 'tight')
        self.assertEqual(info['level'], 'amber')

    def test_sla_pause_extends_deadline(self):
        # 截止 1 小时后，但暂停了 30 分钟，应延长剩余时间避免立即超时
        due_at = timezone.now() + timedelta(hours=1)
        task = Task.objects.create(title='t2', user=self.admin, project=self.project, due_at=due_at, status='on_hold')
        timer = _ensure_sla_timer(task)
        timer.paused_at = timezone.now() - timedelta(minutes=30)
        timer.save(update_fields=['paused_at'])
        info = calculate_sla_info(task)
        self.assertGreater(info['remaining_hours'], 1.2)  # 延长后剩余时间应大于原始 1 小时

    def test_performance_stats_sla_and_leadtime(self):
        cache.clear()
        now = timezone.now()
        # 先创建，再回写时间字段
        t1 = Task.objects.create(title='t1', user=self.admin, project=self.project, status='done', due_at=now)
        Task.objects.filter(id=t1.id).update(created_at=now - timedelta(hours=2), completed_at=now - timedelta(hours=1))
        t1.refresh_from_db()
        t2 = Task.objects.create(title='t2', user=self.admin, project=self.project, status='done', due_at=now - timedelta(hours=1))
        Task.objects.filter(id=t2.id).update(created_at=now - timedelta(hours=4), completed_at=now)
        t2.refresh_from_db()
        stats = report_views._performance_stats()
        self.assertEqual(stats['overall_sla_on_time_rate'], 50.0)
        self.assertIsNotNone(stats['overall_lead_p50'])
        # 项目指标带上 SLA 和 lead time
        project = next((p for p in stats['project_stats'] if p['project'] == self.project.name), None)
        self.assertIsNotNone(project)
        self.assertIn('sla_on_time_rate', project)
        self.assertIn('lead_time_p50', project)
