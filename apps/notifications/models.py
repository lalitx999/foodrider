import uuid
from django.db import models
from apps.users.models import User


class DeviceToken(models.Model):
    """
    ตารางเก็บ FCM Device Token สำหรับส่ง Web Push Notification ไปยัง PWA
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='device_tokens')
    fcm_token = models.CharField(max_length=4096, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'device_tokens'

    def __str__(self):
        return f"{self.user.display_name} - FCM Token ({self.fcm_token[:10]}...)"


class Notification(models.Model):
    """Event จริงในระบบ; FCM เป็น delivery channel ไม่ใช่ source of truth."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return self.title
