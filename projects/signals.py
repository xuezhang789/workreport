
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import ProjectAttachment

@receiver(post_delete, sender=ProjectAttachment)
def delete_project_attachment_file(sender, instance, **kwargs):
    """
    Delete the file from storage when ProjectAttachment is deleted.
    Ensures data consistency between DB and storage.
    """
    if instance.file:
        instance.file.delete(save=False)
