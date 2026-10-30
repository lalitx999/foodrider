from django.contrib import admin
from django.urls import path, include

from apps.payments.views import SlipFileView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.users.urls')),
    path('api/v1/', include('apps.merchants.urls')),
    path('api/v1/', include('apps.orders.urls')),
    path('api/v1/', include('apps.riders.urls')),
    path('api/v1/', include('apps.notifications.urls')),
    path('api/v1/media/slip/<uuid:slip_id>/<str:token>/', SlipFileView.as_view(), name='media-slip'),
    path('api/admin/v1/', include('apps.backoffice.urls')),
]

# P0-11: ห้ามเสิร์ฟ /media/ แบบ public จาก Django อีก
# - ไฟล์สลิปอยู่ใน PRIVATE storage (SLIP_STORAGE_LOCATION) และเข้าถึงผ่าน signed endpoint เท่านั้น
# - production ให้ nginx เป็นผู้เสิร์ฟไฟล์ private ผ่าน X-Accel-Redirect





