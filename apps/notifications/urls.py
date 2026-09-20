from django.urls import path
from apps.notifications.views import RegisterDeviceTokenView, LineWebhookView

urlpatterns = [
    path('notifications/register-device/', RegisterDeviceTokenView.as_view(), name='register-device'),
    path('notifications/line-webhook/', LineWebhookView.as_view(), name='line-webhook'),
]

