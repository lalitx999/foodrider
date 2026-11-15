from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.merchants.models import Merchant
from apps.orders.models import Order, OrderStatus
from apps.riders.live_location import get_live_location, save_live_location
from apps.riders.models import RiderProfile
from apps.users.models import CustomerProfile, User, UserRole

PASSWORD = 'Branch-Pass-2026!'


def branch_payload(**overrides):
    data = {
        'name': 'ร้านทดสอบ สาขา 1',
        'address': '1 ถนนทดสอบ',
        'latitude': 12.9236,
        'longitude': 100.8825,
        'email': 'Branch1@Example.com',
        'phone_number': '0812345678',
        'password': PASSWORD,
        'password_confirm': PASSWORD,
    }
    data.update(overrides)
    return data


def rider_payload(**overrides):
    data = {
        'display_name': 'น้องไรเดอร์',
        'email': 'rider1@example.com',
        'phone_number': '0898765432',
        'vehicle_plate': 'กข 1234',
        'password': PASSWORD,
        'password_confirm': PASSWORD,
    }
    data.update(overrides)
    return data


class AdminStaffApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create(display_name='เจ้าของร้าน', email='owner@example.com', role=UserRole.ADMIN)
        self.client.force_authenticate(self.admin)

    def _make_order(self, merchant, *, rider=None, order_status=OrderStatus.PREPARING, number='ORD-STAFF-1'):
        customer, _ = User.objects.get_or_create(
            email='customer-staff@example.com', defaults={'display_name': 'ลูกค้า', 'role': UserRole.CUSTOMER}
        )
        CustomerProfile.objects.get_or_create(user=customer, defaults={'default_delivery_address': 'บ้าน'})
        return Order.objects.create(
            order_number=number, customer=customer, merchant=merchant, rider=rider, status=order_status,
            subtotal=Decimal('100.00'), delivery_fee=Decimal('30.00'), total_amount=Decimal('130.00'),
            delivery_address='บ้าน', delivery_latitude=Decimal('12.93'), delivery_longitude=Decimal('100.89'),
            delivery_location=Point(100.89, 12.93, srid=4326), delivery_distance_km=Decimal('2.00'),
            rider_delivery_fee=Decimal('25.00'), platform_fee=Decimal('15.00'),
        )

    # ---------- สิทธิ์ ----------

    def test_only_admin_can_use_staff_endpoints(self):
        merchant_user = User.objects.create(display_name='ร้าน', email='m@example.com', role=UserRole.MERCHANT)
        self.client.force_authenticate(merchant_user)
        for name in ('admin-branch-list', 'admin-rider-list'):
            self.assertEqual(self.client.get(reverse(name)).status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(self.client.post(reverse(name), {}, format='json').status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Merchant.objects.exists())

    # ---------- สาขา ----------

    def test_create_branch_then_list(self):
        response = self.client.post(reverse('admin-branch-list'), branch_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        data = response.data['data']
        self.assertEqual(data['email'], 'branch1@example.com')
        self.assertEqual(data['display_name'], 'ร้านทดสอบ สาขา 1')  # ไม่ใส่ชื่อบัญชี = ใช้ชื่อสาขา
        self.assertTrue(data['is_active'])
        self.assertFalse(data['is_open'])

        branch = Merchant.objects.get()
        self.assertEqual(branch.user.role, UserRole.MERCHANT)
        self.assertTrue(branch.user.check_password(PASSWORD))

        listing = self.client.get(reverse('admin-branch-list'))
        self.assertEqual([item['id'] for item in listing.data['data']], [str(branch.id)])
        self.assertNotIn('password', listing.data['data'][0])

    def test_create_branch_rejects_bad_input_without_creating_anything(self):
        cases = [
            branch_payload(password_confirm='something-else'),
            branch_payload(latitude=0, longitude=0),
            branch_payload(latitude=None, longitude=None),
            branch_payload(password='short', password_confirm='short'),
            branch_payload(address=''),
        ]
        for payload in cases:
            response = self.client.post(reverse('admin-branch-list'), payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, payload)
            self.assertFalse(response.data['success'])
        self.assertFalse(Merchant.objects.exists())
        self.assertFalse(User.objects.filter(email='branch1@example.com').exists())

    def test_existing_email_needs_use_existing_and_admin_is_never_converted(self):
        User.objects.create(display_name='ลูกค้าเดิม', email='branch1@example.com', role=UserRole.CUSTOMER)
        response = self.client.post(reverse('admin-branch-list'), branch_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            reverse('admin-branch-list'),
            branch_payload(use_existing=True, password='', password_confirm=''),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        response = self.client.post(
            reverse('admin-branch-list'),
            branch_payload(email='owner@example.com', use_existing=True, password='', password_confirm=''),
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.get(email='owner@example.com').role, UserRole.ADMIN)

    def test_deactivate_branch_closes_store_blocks_login_and_reactivate(self):
        self.client.post(reverse('admin-branch-list'), branch_payload(), format='json')
        branch = Merchant.objects.get()
        branch.is_open = True
        branch.save()
        refresh = RefreshToken.for_user(branch.user)

        response = self.client.patch(reverse('admin-branch-detail', args=[branch.id]), {'is_active': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        branch.refresh_from_db()
        self.assertFalse(branch.is_open)
        self.assertFalse(branch.user.is_active)

        anon = APIClient()
        login = anon.post(reverse('email-login'), {'email': 'branch1@example.com', 'password': PASSWORD}, format='json')
        self.assertNotEqual(login.status_code, status.HTTP_200_OK)
        old_session = anon.post(reverse('token-refresh'), {'refresh': str(refresh)}, format='json')
        self.assertEqual(old_session.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.patch(reverse('admin-branch-detail', args=[branch.id]), {'is_active': True}, format='json')
        self.assertTrue(response.data['data']['is_active'])
        self.assertFalse(response.data['data']['is_open'])  # เปิดร้านเองจากจอครัว
        login = anon.post(reverse('email-login'), {'email': 'branch1@example.com', 'password': PASSWORD}, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_cannot_deactivate_branch_with_open_orders(self):
        self.client.post(reverse('admin-branch-list'), branch_payload(), format='json')
        branch = Merchant.objects.get()
        self._make_order(branch)
        response = self.client.patch(reverse('admin-branch-detail', args=[branch.id]), {'is_active': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        branch.user.refresh_from_db()
        self.assertTrue(branch.user.is_active)

    def test_reset_branch_password(self):
        self.client.post(reverse('admin-branch-list'), branch_payload(), format='json')
        branch = Merchant.objects.get()
        url = reverse('admin-branch-password', args=[branch.id])
        mismatch = self.client.post(url, {'password': 'New-Pass-2026-abc', 'password_confirm': 'x'}, format='json')
        self.assertEqual(mismatch.status_code, status.HTTP_400_BAD_REQUEST)
        weak = self.client.post(url, {'password': 'short', 'password_confirm': 'short'}, format='json')
        self.assertEqual(weak.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(url, {'password': 'New-Pass-2026-abc', 'password_confirm': 'New-Pass-2026-abc'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        branch.user.refresh_from_db()
        self.assertTrue(branch.user.check_password('New-Pass-2026-abc'))

    def test_unknown_branch_returns_404(self):
        response = self.client.patch(
            reverse('admin-branch-detail', args=['00000000-0000-0000-0000-000000000000']), {'is_active': False}, format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ---------- ไรเดอร์ ----------

    def test_create_rider_then_list(self):
        response = self.client.post(reverse('admin-rider-list'), rider_payload(), format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        profile = RiderProfile.objects.get()
        self.assertEqual(profile.user.role, UserRole.RIDER)
        self.assertFalse(profile.is_online)
        listing = self.client.get(reverse('admin-rider-list')).data['data']
        self.assertEqual(listing[0]['vehicle_plate'], 'กข 1234')
        self.assertIsNone(listing[0]['last_location_at'])

    def test_create_rider_requires_plate_and_phone(self):
        for payload in (rider_payload(vehicle_plate=''), rider_payload(phone_number='')):
            response = self.client.post(reverse('admin-rider-list'), payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(RiderProfile.objects.exists())

    def test_deactivate_rider_goes_offline_and_clears_live_location(self):
        self.client.post(reverse('admin-rider-list'), rider_payload(), format='json')
        profile = RiderProfile.objects.get()
        profile.is_online = True
        profile.save()
        save_live_location(profile, {'lat': 12.93, 'lng': 100.88, 'accuracy': 10, 'heading': None, 'speed': None})

        response = self.client.patch(reverse('admin-rider-detail', args=[profile.id]), {'is_active': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        profile.refresh_from_db()
        self.assertFalse(profile.is_online)
        self.assertFalse(profile.user.is_active)
        self.assertIsNone(get_live_location(profile.user_id))

    def test_cannot_deactivate_rider_while_delivering(self):
        self.client.post(reverse('admin-branch-list'), branch_payload(), format='json')
        self.client.post(reverse('admin-rider-list'), rider_payload(), format='json')
        profile = RiderProfile.objects.get()
        self._make_order(Merchant.objects.get(), rider=profile.user, order_status=OrderStatus.DELIVERING)
        response = self.client.patch(reverse('admin-rider-detail', args=[profile.id]), {'is_active': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_password_reset_is_only_for_staff_accounts(self):
        from apps.users.staff_accounts import StaffAccountError, reset_staff_password

        with self.assertRaises(StaffAccountError):
            reset_staff_password(self.admin, 'New-Pass-2026-abc')
