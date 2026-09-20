import uuid
from django.db import models
from apps.users.models import User


class DeviceToken(models.Model):
    """
    ตารางเก็บ FCM Device Token สำหรับส่ง Web Push Notification ไปยัง PWA
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='device_tokens')
    fcm_token = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'device_tokens'

    def __str__(self):
        return f"{self.user.display_name} - FCM Token ({self.fcm_token[:10]}...)"
