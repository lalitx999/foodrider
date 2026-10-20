from decimal import Decimal
from rest_framework.permissions import BasePermission
from django.contrib.gis.geos import Point
from apps.users.models import UserRole, ApplicationStatus


class HasMerchantProfile(BasePermission):
    """Allow only an authenticated merchant that owns a Merchant profile."""

    message = 'บัญชีนี้ไม่มีสิทธิ์จัดการร้านค้า'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False

        # If user has an approved merchant application, ensure merchant_profile and role are synced
        if hasattr(user, 'merchant_application') and user.merchant_application.status == ApplicationStatus.APPROVED:
            if user.role != UserRole.MERCHANT and user.role != UserRole.ADMIN:
                user.role = UserRole.MERCHANT
                user.save(update_fields=['role', 'updated_at'])
            if not hasattr(user, 'merchant_profile'):
                from apps.merchants.models import Merchant
                app = user.merchant_application
                lat = app.latitude if app.latitude is not None else Decimal('12.9276')
                lng = app.longitude if app.longitude is not None else Decimal('100.8771')
                img_url = ''
                if app.storefront_image:
                    try:
                        img_url = app.storefront_image.url
                    except Exception:
                        img_url = ''
                if not img_url:
                    img_url = 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=600&q=80'

                Merchant.objects.get_or_create(
                    user=user,
                    defaults={
                        'name': app.store_name or 'ร้านค้าของฉัน',
                        'image_url': img_url,
                        'phone_number': app.phone_number or '',
                        'address': app.address or '',
                        'latitude': lat,
                        'longitude': lng,
                        'location': Point(float(lng), float(lat), srid=4326),
                        'bank_account_name': app.bank_account_name or 'บัญชีร้านค้า',
                        'bank_account_number': app.bank_account_number or '0000000000',
                        'bank_name': app.bank_name or 'พร้อมเพย์',
                    }
                )

        if user.role in {UserRole.MERCHANT, UserRole.ADMIN}:
            # If admin accesses merchant panel, provide an admin store profile if not exists
            if user.role == UserRole.ADMIN and not hasattr(user, 'merchant_profile'):
                from apps.merchants.models import Merchant
                Merchant.objects.get_or_create(
                    user=user,
                    defaults={
                        'name': 'ร้านทดสอบ (Admin)',
                        'image_url': 'https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=600&q=80',
                        'phone_number': '0800000000',
                        'address': 'สำนักงานใหญ่',
                        'latitude': Decimal('12.9276'),
                        'longitude': Decimal('100.8771'),
                        'location': Point(100.8771, 12.9276, srid=4326),
                        'bank_account_name': 'Admin Store',
                        'bank_account_number': '0000000000',
                        'bank_name': 'พร้อมเพย์',
                    }
                )
            return hasattr(user, 'merchant_profile')

        return False


class HasRiderProfile(BasePermission):
    """Allow only an authenticated rider that owns a RiderProfile."""

    message = 'บัญชีนี้ไม่มีสิทธิ์ใช้งานระบบไรเดอร์'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False

        if hasattr(user, 'rider_application') and user.rider_application.status == ApplicationStatus.APPROVED:
            if user.role != UserRole.RIDER and user.role != UserRole.ADMIN:
                user.role = UserRole.RIDER
                user.save(update_fields=['role', 'updated_at'])
            if not hasattr(user, 'rider_profile'):
                from apps.riders.models import RiderProfile
                app = user.rider_application
                RiderProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'vehicle_plate': app.vehicle_plate or 'ไม่ระบุ',
                        'bank_account_name_encrypted': app.bank_account_name_encrypted,
                        'bank_account_number_encrypted': app.bank_account_number_encrypted,
                        'bank_name_encrypted': app.bank_name_encrypted,
                    }
                )

        if user.role in {UserRole.RIDER, UserRole.ADMIN}:
            if user.role == UserRole.ADMIN and not hasattr(user, 'rider_profile'):
                from apps.riders.models import RiderProfile
                RiderProfile.objects.get_or_create(
                    user=user,
                    defaults={'vehicle_plate': 'ADMIN-01'}
                )
            return hasattr(user, 'rider_profile')

        return False


class HasCustomerProfile(BasePermission):
    message = 'บัญชีนี้ไม่มีสิทธิ์สั่งอาหาร'

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active):
            return False
        if user.role in {UserRole.CUSTOMER, UserRole.ADMIN}:
            if not hasattr(user, 'customer_profile'):
                from apps.users.models import CustomerProfile
                CustomerProfile.objects.get_or_create(
                    user=user,
                    defaults={'default_delivery_address': 'ที่อยู่เริ่มต้น'}
                )
            return hasattr(user, 'customer_profile')
        return False
