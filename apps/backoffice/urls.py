from django.urls import path

from apps.backoffice.views import (
    SlipApproveView,
    SlipDetailView,
    SlipListView,
    SlipRejectView,
)

urlpatterns = [
    path('slips/', SlipListView.as_view(), name='admin-slip-list'),
    path('slips/<uuid:slip_id>/', SlipDetailView.as_view(), name='admin-slip-detail'),
    path('slips/<uuid:slip_id>/approve/', SlipApproveView.as_view(), name='admin-slip-approve'),
    path('slips/<uuid:slip_id>/reject/', SlipRejectView.as_view(), name='admin-slip-reject'),
]
