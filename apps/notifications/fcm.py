import json
import logging
import os
from django.utils import timezone
from apps.notifications.models import DeviceToken, Notification

logger = logging.getLogger(__name__)


class FCMConfigurationError(Exception):
    pass


def _messaging_client():
    service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
    if not service_account_json:
        raise FCMConfigurationError('ยังไม่ได้ตั้งค่า FIREBASE_SERVICE_ACCOUNT_JSON')
    import firebase_admin
    from firebase_admin import credentials, messaging
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(credentials.Certificate(json.loads(service_account_json)))
    return messaging


def create_and_send_notification(*, user, title: str, body: str, data: dict | None = None) -> Notification:
    notification = Notification.objects.create(user=user, title=title, body=body, data=data or {})
    tokens = list(DeviceToken.objects.filter(user=user, is_active=True).values_list('fcm_token', flat=True))
    if not tokens:
        return notification
    try:
        messaging = _messaging_client()
    except FCMConfigurationError:
        return notification
    delivered = 0
    for token in tokens:
        try:
            messaging.send(messaging.Message(token=token, notification=messaging.Notification(title=title, body=body), data={key: str(value) for key, value in notification.data.items()}))
            delivered += 1
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
            DeviceToken.objects.filter(fcm_token=token).update(is_active=False)
        except Exception:
            logger.exception('FCM delivery failed for notification %s', notification.id)
    if delivered:
        notification.sent_at = timezone.now()
        notification.save(update_fields=['sent_at'])
    return notification
