
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import TaskAttachment

@receiver(post_delete, sender=TaskAttachment)
def delete_task_attachment_file(sender, instance, **kwargs):
    """
    Delete the file from storage when TaskAttachment is deleted.
    Ensures data consistency between DB and storage.
    """
    if instance.file:
        instance.file.delete(save=False)
