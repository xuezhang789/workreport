from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0004_taskcomment_tasks_taskc_task_id_8332b2_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='version',
            field=models.PositiveIntegerField(default=1, verbose_name='版本号'),
        ),
    ]
