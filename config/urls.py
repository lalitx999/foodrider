from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.users.urls')),
    path('api/v1/', include('apps.merchants.urls')),
    path('api/v1/', include('apps.orders.urls')),
    path('api/v1/', include('apps.riders.urls')),
    path('api/v1/', include('apps.notifications.urls')),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]





