from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.users.urls')),
    path('api/v1/', include('apps.merchants.urls')),
    path('api/v1/', include('apps.orders.urls')),
    path('api/v1/', include('apps.riders.urls')),
    path('api/v1/', include('apps.notifications.urls')),
]





