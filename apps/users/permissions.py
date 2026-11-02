from rest_framework.permissions import BasePermission
from apps.users.models import UserRole


class IsAdminRole(BasePermission):
    """อนุญาตเฉพาะผู้ใช้ที่ role = ADMIN (ไม่ใช่แค่ is_staff) — P0-08"""

    message = 'เฉพาะผู้ดูแลระบบ (ADMIN) เท่านั้น'

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.role == UserRole.ADMIN)


class IsStaffOrAdminRole(BasePermission):
    """ใช้กับ endpoint ที่ให้ Django staff เข้าได้ด้วย (read-only/admin tooling)"""

    message = 'เฉพาะผู้ดูแลระบบเท่านั้น'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and (user.is_staff or user.role == UserRole.ADMIN)
        )


class HasMerchantProfile(BasePermission):
    """
    อนุญาตเฉพาะผู้ใช้ที่มี Merchant profile แล้วเท่านั้น — ตรวจอย่างเดียว ไม่เขียน DB (P0-08)
    profile ถูกสร้างตอนแอดมินอนุมัติ (`approve_role_change_request`)
    ข้อมูลเก่าที่ค้าง ให้รัน `manage.py sync_user_roles`
    """

    message = 'บัญชีนี้ไม่มีสิทธิ์จัดการร้านค้า'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active
            and user.role in {UserRole.MERCHANT, UserRole.ADMIN}
            and hasattr(user, 'merchant_profile')
        )


class HasRiderProfile(BasePermission):
    """อนุญาตเฉพาะผู้ใช้ที่มี RiderProfile แล้วเท่านั้น — ตรวจอย่างเดียว ไม่เขียน DB (P0-08)"""

    message = 'บัญชีนี้ไม่มีสิทธิ์ใช้งานระบบไรเดอร์'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active
            and user.role in {UserRole.RIDER, UserRole.ADMIN}
            and hasattr(user, 'rider_profile')
        )


class HasCustomerProfile(BasePermission):
    """อนุญาตเฉพาะผู้ใช้ที่มี CustomerProfile แล้วเท่านั้น — ตรวจอย่างเดียว ไม่เขียน DB (P0-08)"""

    message = 'บัญชีนี้ไม่มีสิทธิ์สั่งอาหาร'

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active
            and user.role in {UserRole.CUSTOMER, UserRole.ADMIN}
            and hasattr(user, 'customer_profile')
        )
