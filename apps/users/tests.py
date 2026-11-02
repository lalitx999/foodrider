from django.test import TestCase
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import (
    ApplicationStatus, MerchantApplication, RiderApplication, RoleChangeRequest,
    RoleChangeStatus, User, UserRole,
)
from apps.users.services import approve_role_change_request, reject_role_change_request


class AuthenticationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse('email-register')
        self.google_verify_url = reverse('google-verify')
        self.profile_url = reverse('user-profile')
        self.set_role_url = reverse('set-role')

    def test_email_register_missing_payload(self):
        response = self.client.post(self.register_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'INVALID_PAYLOAD')

    def test_google_verify_missing_payload(self):
        """ทดสอบการส่ง payload ว่างเปล่าของ Google ต้องได้ 400 BAD REQUEST"""
        response = self.client.post(self.google_verify_url, {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error_code'], 'INVALID_PAYLOAD')

    def test_email_register_creates_unassigned_user(self):
        response = self.client.post(self.register_url, {'display_name': 'Somchai', 'email': 'somchai@example.com', 'password': 'safe-password-123', 'password_confirm': 'safe-password-123'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        self.assertIn('access', response.data['data'])
        self.assertIn('refresh', response.data['data'])

        # ตรวจสอบการสร้าง User ในฐานข้อมูล
        user = User.objects.get(email='somchai@example.com')
        self.assertEqual(user.display_name, 'Somchai')
        self.assertEqual(user.role, UserRole.UNASSIGNED)

    def test_profile_requires_authentication(self):
        """ทดสอบเข้าถึง Profile โดยไม่ส่ง JWT Token ต้องได้ 401 UNAUTHORIZED"""
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_with_valid_jwt(self):
        """ทดสอบเข้าถึง Profile พร้อม JWT Token ต้องได้ข้อมูล 200 OK"""
        user = User.objects.create(
            display_name='Test User',
            email='customer@example.com',
            role=UserRole.CUSTOMER
        )
        self.client.force_authenticate(user=user)
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['display_name'], 'Test User')


class RoleChangeRequestServiceTests(TestCase):
    def setUp(self):
        self.reviewer = User.objects.create(display_name='Admin Reviewer', role=UserRole.ADMIN, is_staff=True)
        self.customer = User.objects.create(display_name='Customer User', role=UserRole.CUSTOMER)

    def test_approve_rider_request_creates_profile_and_switches_role(self):
        application = RiderApplication.objects.create(
            user=self.customer,
            full_name='Customer User',
            phone_number='0800000000',
            vehicle_plate='1กข-1234',
            driver_license_image='rider-applications/licenses/license.jpg',
            vehicle_image='rider-applications/vehicles/vehicle.jpg',
            status=ApplicationStatus.PENDING_REVIEW,
        )
        role_request = RoleChangeRequest.objects.create(
            user=self.customer,
            current_role=UserRole.CUSTOMER,
            requested_role=UserRole.RIDER,
            rider_application=application,
        )

        approve_role_change_request(role_request.id, self.reviewer, 'เอกสารครบถ้วน')

        self.customer.refresh_from_db()
        role_request.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.RIDER)
        self.assertTrue(hasattr(self.customer, 'rider_profile'))
        self.assertEqual(self.customer.rider_profile.vehicle_plate, '1กข-1234')
        self.assertEqual(application.status, ApplicationStatus.APPROVED)
        self.assertEqual(role_request.status, RoleChangeStatus.APPROVED)
        self.assertEqual(role_request.reviewed_by, self.reviewer)

    def test_reject_request_preserves_current_role(self):
        application = RiderApplication.objects.create(
            user=self.customer,
            full_name='Customer User',
            phone_number='0800000000',
            vehicle_plate='1กข-1234',
            driver_license_image='rider-applications/licenses/license.jpg',
            vehicle_image='rider-applications/vehicles/vehicle.jpg',
            status=ApplicationStatus.PENDING_REVIEW,
        )
        role_request = RoleChangeRequest.objects.create(
            user=self.customer,
            current_role=UserRole.CUSTOMER,
            requested_role=UserRole.RIDER,
            rider_application=application,
        )

        reject_role_change_request(role_request.id, self.reviewer, 'เอกสารไม่ครบ')

        self.customer.refresh_from_db()
        role_request.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.CUSTOMER)
        self.assertEqual(application.status, ApplicationStatus.REJECTED)
        self.assertEqual(role_request.status, RoleChangeStatus.REJECTED)
        self.assertEqual(role_request.admin_note, 'เอกสารไม่ครบ')


class AuthThrottleTests(TestCase):
    """P0-09: login 10 ครั้ง/นาที, register 5 ครั้ง/นาที (ScopedRateThrottle)"""

    def setUp(self):
        self.client = APIClient()
        cache.clear()  # กัน throttle ค้างจาก test อื่น

    def tearDown(self):
        cache.clear()

    def test_login_throttled_after_ten_attempts(self):
        url = reverse('email-login')
        payload = {'email': 'nobody@example.com', 'password': 'wrong-password'}

        for _ in range(10):
            response = self.client.post(url, payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        throttled = self.client.post(url, payload, format='json')
        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_register_throttled_after_five_attempts(self):
        url = reverse('email-register')
        payload = {}

        for _ in range(5):
            response = self.client.post(url, payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        throttled = self.client.post(url, payload, format='json')
        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)



class PermissionSideEffectTests(TestCase):
    """P0-08: permission และ GET ต้องตรวจอย่างเดียว ห้ามสร้าง/แก้ข้อมูล"""

    def setUp(self):
        from apps.merchants.models import Merchant
        from apps.riders.models import RiderProfile
        from apps.users.models import CustomerProfile
        self.Merchant, self.RiderProfile, self.CustomerProfile = Merchant, RiderProfile, CustomerProfile
        self.client = APIClient()

    def _row_counts(self):
        return (self.Merchant.objects.count(), self.RiderProfile.objects.count(),
                self.CustomerProfile.objects.count())

    def test_admin_without_profiles_gets_403_and_nothing_created(self):
        admin = User.objects.create(display_name='Admin', email='a@example.com', role=UserRole.ADMIN, is_staff=True)
        self.client.force_authenticate(admin)
        before = self._row_counts()

        self.assertEqual(self.client.get(reverse('merchant-dashboard')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('rider-profile')).status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(self._row_counts(), before)

    def test_approved_application_without_profile_is_not_auto_fixed(self):
        user = User.objects.create(display_name='Shop', email='shop@example.com', role=UserRole.CUSTOMER)
        MerchantApplication.objects.create(
            user=user, store_name='ร้านทดสอบ', phone_number='0800000000', address='ที่อยู่ทดสอบ',
            storefront_image='merchant-applications/storefronts/s.jpg', status=ApplicationStatus.APPROVED,
        )
        self.client.force_authenticate(user)
        before = self._row_counts()

        self.assertEqual(self.client.get(reverse('merchant-dashboard')).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('user-profile')).status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.CUSTOMER)
        self.assertEqual(self._row_counts(), before)

    def test_admin_role_can_access_backoffice_without_is_staff(self):
        admin = User.objects.create(display_name='Admin2', email='a2@example.com', role=UserRole.ADMIN, is_staff=False)
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get(reverse('admin-slip-list')).status_code, status.HTTP_200_OK)

    def test_staff_without_admin_role_cannot_access_backoffice(self):
        staff = User.objects.create(display_name='Staff', email='s@example.com', role=UserRole.CUSTOMER, is_staff=True)
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.get(reverse('admin-slip-list')).status_code, status.HTTP_403_FORBIDDEN)


class SyncUserRolesCommandTests(TestCase):
    """P0-08: คำสั่ง sync_user_roles เติมข้อมูลที่ขาด และรันซ้ำได้"""

    def _call(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('sync_user_roles', *args, stdout=out)
        return out.getvalue()

    def _approved_shop(self, email, role, with_location=True):
        user = User.objects.create(display_name='Shop', email=email, role=role)
        MerchantApplication.objects.create(
            user=user, store_name='ร้านทดสอบ', phone_number='0800000000', address='ที่อยู่ทดสอบ',
            latitude=13.7563 if with_location else None, longitude=100.5018 if with_location else None,
            storefront_image='merchant-applications/storefronts/s.jpg', status=ApplicationStatus.APPROVED,
        )
        return user

    def test_skips_shop_without_location(self):
        from apps.merchants.models import Merchant
        user = self._approved_shop('nolocation@example.com', UserRole.CUSTOMER, with_location=False)
        output = self._call()
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.CUSTOMER)  # ไม่เปลี่ยน role ถ้าสร้างร้านไม่ได้
        self.assertEqual(Merchant.objects.count(), 0)
        self.assertIn('ยังไม่มีพิกัดร้าน', output)

    def test_creates_missing_profile_and_upgrades_customer(self):
        user = self._approved_shop('shop1@example.com', UserRole.CUSTOMER)
        self._call()
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.MERCHANT)
        self.assertTrue(hasattr(user, 'merchant_profile'))

    def test_idempotent(self):
        from apps.merchants.models import Merchant
        self._approved_shop('shop2@example.com', UserRole.CUSTOMER)
        self._call()
        self._call()
        self.assertEqual(Merchant.objects.count(), 1)

    def test_dry_run_changes_nothing(self):
        from apps.merchants.models import Merchant
        user = self._approved_shop('shop3@example.com', UserRole.CUSTOMER)
        self._call('--dry-run')
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.CUSTOMER)
        self.assertEqual(Merchant.objects.count(), 0)

    def test_does_not_switch_rider_to_merchant(self):
        user = self._approved_shop('shop4@example.com', UserRole.RIDER)
        output = self._call()
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.RIDER)
        self.assertIn('ตรวจเอง', output)

    def test_never_touches_admin(self):
        user = self._approved_shop('shop5@example.com', UserRole.ADMIN)
        self._call()
        user.refresh_from_db()
        self.assertEqual(user.role, UserRole.ADMIN)
        self.assertFalse(hasattr(user, 'merchant_profile'))


class LogoutTests(TestCase):
    """P0-07: logout ต้อง blacklist refresh token"""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create(display_name='Logout User', email='logout@example.com', role=UserRole.CUSTOMER)

    def test_logout_blacklists_refresh(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = str(RefreshToken.for_user(self.user))

        response = self.client.post(reverse('logout'), {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(reverse('token-refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_twice_is_ok(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = str(RefreshToken.for_user(self.user))
        self.client.post(reverse('logout'), {'refresh': refresh}, format='json')
        response = self.client.post(reverse('logout'), {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_requires_refresh(self):
        response = self.client.post(reverse('logout'), {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'REFRESH_TOKEN_REQUIRED')


class MerchantApprovalLocationTests(TestCase):
    """อนุมัติร้านต้องมีพิกัดจริง — ไม่ใช้พิกัดกลางเมืองแทน (ระบบใช้ได้หลายพื้นที่)"""

    def setUp(self):
        self.reviewer = User.objects.create(display_name='Admin', email='rev@example.com', role=UserRole.ADMIN, is_staff=True)
        self.customer = User.objects.create(display_name='Shop Owner', email='shopowner@example.com', role=UserRole.CUSTOMER)

    def _request(self, latitude, longitude):
        application = MerchantApplication.objects.create(
            user=self.customer, store_name='ร้านใหม่', phone_number='0800000000', address='ที่อยู่',
            latitude=latitude, longitude=longitude,
            storefront_image='merchant-applications/storefronts/s.jpg', status=ApplicationStatus.PENDING_REVIEW,
            bank_account_name='เจ้าของ', bank_account_number='1234567890', bank_name='กสิกรไทย',
        )
        return RoleChangeRequest.objects.create(
            user=self.customer, current_role=UserRole.CUSTOMER, requested_role=UserRole.MERCHANT, merchant_application=application,
        )

    def test_approve_without_location_is_refused(self):
        from apps.merchants.models import Merchant
        from apps.users.services import RoleChangeApprovalError
        role_request = self._request(None, None)
        with self.assertRaises(RoleChangeApprovalError):
            approve_role_change_request(role_request.id, self.reviewer)
        self.customer.refresh_from_db()
        role_request.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.CUSTOMER)
        self.assertEqual(role_request.status, RoleChangeStatus.PENDING)
        self.assertFalse(Merchant.objects.filter(user=self.customer).exists())

    def test_approve_with_location_pins_real_point(self):
        role_request = self._request(13.7563, 100.5018)
        approve_role_change_request(role_request.id, self.reviewer)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.MERCHANT)
        self.assertAlmostEqual(self.customer.merchant_profile.location.y, 13.7563, places=4)
        self.assertAlmostEqual(self.customer.merchant_profile.location.x, 100.5018, places=4)
