
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from .models import TaskAttachment, Task

@receiver(post_delete, sender=TaskAttachment)
def delete_task_attachment_file(sender, instance, **kwargs):
    """
    Delete the file from storage when TaskAttachment is deleted.
    Ensures data consistency between DB and storage.
    """
    if instance.file:
        instance.file.delete(save=False)

@receiver(post_save, sender=Task)
@receiver(post_delete, sender=Task)
def update_project_progress_signal(sender, instance, **kwargs):
    """
    Update project progress when a task is created, updated, or deleted.
    """
    if instance.project:
        instance.project.update_progress()
