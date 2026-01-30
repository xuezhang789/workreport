import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

@dataclass
class NotificationItem:
    label: str
    value: str
    old_value: Optional[str] = None
    highlight: bool = False

@dataclass
class NotificationAction:
    label: str
    url: str
    style: str = "primary" # primary, secondary, danger, link

@dataclass
class NotificationContent:
    title: str
    body: str
    subject: Optional[str] = None # Defaults to title if not provided
    subtitle: Optional[str] = None
    items: List[NotificationItem] = field(default_factory=list)
    actions: List[NotificationAction] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self):
        return asdict(self)
    
    @property
    def email_subject(self):
        return self.subject or self.title

class NotificationTemplateService:
    @staticmethod
    def render_email(content: NotificationContent) -> str:
        """
        Render the notification content into an HTML email.
        """
        context = {
            'content': content,
            'site_name': getattr(settings, 'SITE_NAME', 'WorkReport'),
            'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000'),
            'year': timezone.now().year,
        }
        return render_to_string('emails/notification_base.html', context)
    
    @staticmethod
    def render_to_dict(content: NotificationContent) -> Dict:
        """
        Convert content to dictionary for JSON serialization (e.g. for WebSocket/Frontend).
        """
        return content.to_dict()
