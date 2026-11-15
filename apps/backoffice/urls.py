from django.urls import path

from apps.backoffice.staff_views import (
    AdminBranchDetailView,
    AdminBranchListView,
    AdminBranchPasswordView,
    AdminRiderDetailView,
    AdminRiderListView,
    AdminRiderPasswordView,
)
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
    # Module 33 · S-6: สาขาและไรเดอร์
    path('branches/', AdminBranchListView.as_view(), name='admin-branch-list'),
    path('branches/<uuid:pk>/', AdminBranchDetailView.as_view(), name='admin-branch-detail'),
    path('branches/<uuid:pk>/password/', AdminBranchPasswordView.as_view(), name='admin-branch-password'),
    path('riders/', AdminRiderListView.as_view(), name='admin-rider-list'),
    path('riders/<uuid:pk>/', AdminRiderDetailView.as_view(), name='admin-rider-detail'),
    path('riders/<uuid:pk>/password/', AdminRiderPasswordView.as_view(), name='admin-rider-password'),
]
