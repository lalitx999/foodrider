from django.urls import path
from apps.notifications.views import RegisterDeviceTokenView

urlpatterns = [
    path('notifications/register-device/', RegisterDeviceTokenView.as_view(), name='register-device'),
]
