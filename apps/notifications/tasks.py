import logging
from celery import shared_task
from apps.users.models import User
from apps.notifications.fcm import create_and_send_notification

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_push_notification_task(self, user_id, title: str, body: str, data: dict = None):
    """
    Background Task สำหรับส่ง FCM Push Notification ไปยังอุปกรณ์ PWA ของผู้ใช้
    """
    try:
        user = User.objects.get(id=user_id)
        create_and_send_notification(user=user, title=title, body=body, data=data or {})
        return f"Notification sent to user {user_id}"
    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found for push notification")
        return f"User {user_id} not found"
    except Exception as exc:
        logger.exception(f"Error sending push notification to user {user_id}: {exc}")
        raise self.retry(exc=exc, countdown=5)
