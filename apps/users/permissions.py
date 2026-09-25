from rest_framework.permissions import BasePermission

from apps.users.models import UserRole


class HasMerchantProfile(BasePermission):
    """Allow only an authenticated merchant that owns a Merchant profile."""

    message = 'บัญชีนี้ไม่มีสิทธิ์จัดการร้านค้า'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.role == UserRole.MERCHANT
            and hasattr(user, 'merchant_profile')
        )


class HasRiderProfile(BasePermission):
    """Allow only an authenticated rider that owns a RiderProfile."""

    message = 'บัญชีนี้ไม่มีสิทธิ์ใช้งานระบบไรเดอร์'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.role == UserRole.RIDER
            and hasattr(user, 'rider_profile')
        )


class HasCustomerProfile(BasePermission):
    message = 'บัญชีนี้ไม่มีสิทธิ์สั่งอาหาร'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.role == UserRole.CUSTOMER and hasattr(user, 'customer_profile'))
