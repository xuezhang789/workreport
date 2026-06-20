from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditLogArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_id', models.PositiveIntegerField(unique=True, verbose_name='原审计日志ID')),
                ('user_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='用户ID快照')),
                ('operator_name', models.CharField(blank=True, max_length=150, verbose_name='操作人姓名')),
                ('action', models.CharField(max_length=20, verbose_name='动作')),
                ('result', models.CharField(default='success', max_length=10, verbose_name='结果')),
                ('ip', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP地址')),
                ('target_type', models.CharField(blank=True, max_length=100, verbose_name='对象类型')),
                ('target_id', models.CharField(blank=True, max_length=100, verbose_name='对象ID')),
                ('target_label', models.CharField(blank=True, max_length=255, verbose_name='对象名称')),
                ('summary', models.TextField(blank=True, verbose_name='摘要')),
                ('details', models.JSONField(blank=True, default=dict, verbose_name='详情')),
                ('project_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='关联项目ID快照')),
                ('task_id', models.PositiveIntegerField(blank=True, null=True, verbose_name='关联任务ID快照')),
                ('created_at', models.DateTimeField(verbose_name='原记录时间')),
                ('archived_at', models.DateTimeField(auto_now_add=True, verbose_name='归档时间')),
            ],
            options={
                'verbose_name': '审计日志归档',
                'verbose_name_plural': '审计日志归档',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['created_at'], name='audit_audit_created_28cd81_idx'),
                    models.Index(fields=['archived_at'], name='audit_audit_archive_282b31_idx'),
                    models.Index(fields=['action'], name='audit_audit_action_75f18d_idx'),
                    models.Index(fields=['target_type', 'target_id'], name='audit_audit_target__47038d_idx'),
                    models.Index(fields=['project_id', 'created_at'], name='audit_audit_project_9b5716_idx'),
                    models.Index(fields=['task_id', 'created_at'], name='audit_audit_task_id_132b83_idx'),
                ],
            },
        ),
    ]
