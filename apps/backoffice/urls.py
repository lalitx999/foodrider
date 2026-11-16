from django.urls import path

from apps.backoffice.branch_views import (
    AdminBankChangeApproveView,
    AdminBankChangeListView,
    AdminBankChangeRejectView,
    AdminBranchProfileView,
)
from apps.backoffice.dashboard_views import AdminDashboardView
from apps.backoffice.data_views import (
    AdminDataActionView,
    AdminDataTablesView,
    AdminDataTableView,
    AdminDeliveryProofFileView,
)
from apps.backoffice.menu_views import (
    AdminBranchMenuView,
    AdminCategoryCreateView,
    AdminCategoryDetailView,
    AdminMenuItemCreateView,
    AdminMenuItemDetailView,
)
from apps.backoffice.order_views import (
    AdminAuditLogListView,
    AdminOrderAssignRiderView,
    AdminOrderCancelView,
    AdminOrderDetailView,
    AdminOrderListView,
    AdminOrderStatusView,
)
from apps.backoffice.user_views import (
    AdminUserDetailView,
    AdminUserListView,
    AdminUserPasswordView,
    AdminUserRoleView,
)
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
    # Module 32 เฟส B: B2 ออเดอร์ · B1 บันทึกการแก้ไข
    path('orders/', AdminOrderListView.as_view(), name='admin-order-list'),
    path('orders/<uuid:order_id>/', AdminOrderDetailView.as_view(), name='admin-order-detail'),
    path('orders/<uuid:order_id>/cancel/', AdminOrderCancelView.as_view(), name='admin-order-cancel'),
    path('orders/<uuid:order_id>/status/', AdminOrderStatusView.as_view(), name='admin-order-status'),
    path('orders/<uuid:order_id>/assign-rider/', AdminOrderAssignRiderView.as_view(), name='admin-order-assign-rider'),
    path('audit-logs/', AdminAuditLogListView.as_view(), name='admin-audit-log-list'),
    # B3 เมนู
    path('branches/<uuid:branch_id>/menu/', AdminBranchMenuView.as_view(), name='admin-branch-menu'),
    path('branches/<uuid:branch_id>/categories/', AdminCategoryCreateView.as_view(), name='admin-category-create'),
    path('branches/<uuid:branch_id>/menu-items/', AdminMenuItemCreateView.as_view(), name='admin-menu-item-create'),
    path('categories/<uuid:category_id>/', AdminCategoryDetailView.as_view(), name='admin-category-detail'),
    path('menu-items/<uuid:item_id>/', AdminMenuItemDetailView.as_view(), name='admin-menu-item-detail'),
    # B4 ข้อมูลสาขา + บัญชีรับเงิน
    path('branches/<uuid:branch_id>/profile/', AdminBranchProfileView.as_view(), name='admin-branch-profile'),
    path('bank-changes/', AdminBankChangeListView.as_view(), name='admin-bank-change-list'),
    path('bank-changes/<uuid:change_id>/approve/', AdminBankChangeApproveView.as_view(), name='admin-bank-change-approve'),
    path('bank-changes/<uuid:change_id>/reject/', AdminBankChangeRejectView.as_view(), name='admin-bank-change-reject'),
    # B5 ผู้ใช้
    path('users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('users/<uuid:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('users/<uuid:user_id>/role/', AdminUserRoleView.as_view(), name='admin-user-role'),
    path('users/<uuid:user_id>/password/', AdminUserPasswordView.as_view(), name='admin-user-password'),
    # B6 ตารางอื่น + รูปหลักฐานการส่ง
    path('data/', AdminDataTablesView.as_view(), name='admin-data-tables'),
    path('data/<slug:key>/', AdminDataTableView.as_view(), name='admin-data-table'),
    path('data/<slug:key>/<uuid:pk>/<slug:action>/', AdminDataActionView.as_view(), name='admin-data-action'),
    path('delivery-proofs/<uuid:proof_id>/<slug:kind>/<str:token>/', AdminDeliveryProofFileView.as_view(), name='admin-delivery-proof-file'),
    # B7 แดชบอร์ด
    path('dashboard/', AdminDashboardView.as_view(), name='admin-dashboard'),
]
