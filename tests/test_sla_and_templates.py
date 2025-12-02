import json
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from reports.models import Project, DailyReport, Task, SystemSetting, ReportTemplateVersion
from reports import views as report_views


class CacheAndTemplateTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='pass', is_staff=True)
        self.client.login(username='admin', password='pass')
        self.project = Project.objects.create(name='P1', code='P1')

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
        from django.core.cache import cache
        cache.set('performance_stats_v1', {'dummy': True})
        t = Task.objects.first()
        t.title = 't1-updated'
        t.save()
        self.assertIsNone(cache.get('performance_stats_v1'))

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
            self.assertIn("数据量过大", resp.content.decode())
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

    def test_sla_threshold_display_in_task_list(self):
        # 创建即将超时的任务以触发 SLA 提示
        t = Task.objects.create(title='t1', user=self.admin, project=self.project)
        Task.objects.filter(id=t.id).update(created_at=timezone.now() - timedelta(hours=23))
        resp = self.client.get(reverse('reports:task_list'))
        self.assertContains(resp, "SLA 阈值")

    def test_sla_threshold_display_in_performance_board(self):
        resp = self.client.get(reverse('reports:performance_board'))
        self.assertContains(resp, "SLA 阈值")
