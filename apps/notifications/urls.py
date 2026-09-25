from django.urls import path
from apps.notifications.views import RegisterDeviceTokenView, UnregisterDeviceTokensView, NotificationListView

urlpatterns = [
    path('notifications/register-device/', RegisterDeviceTokenView.as_view(), name='register-device'),
    path('notifications/unregister-device/', UnregisterDeviceTokensView.as_view(), name='unregister-device'),
    path('notifications/', NotificationListView.as_view(), name='notification-list'),
]
