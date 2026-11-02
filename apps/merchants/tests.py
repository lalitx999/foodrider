import io
import os
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

from cryptography.fernet import Fernet
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.contrib.gis.geos import Point
from PIL import Image
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import User, UserRole
from apps.merchants.models import BankChangeStatus, Category, Merchant, MerchantBankChangeRequest, MenuItem, MenuOption
from apps.merchants.services import BankChangeError, approve_bank_change, reject_bank_change


class MerchantApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # สร้าง User สำหรับเจ้าของร้าน
        self.merchant_user = User.objects.create(
            display_name='Merchant Owner',
            role=UserRole.MERCHANT
        )

        # สร้าง ร้านค้าที่ 1 (เชียงใหม่ - นิมมาน)
        self.merchant_nimman = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านกาแฟ นิมมาน',
            image_url='https://example.com/nimman.jpg',
            phone_number='0812345678',
            address='นิมมาน ซอย 9',
            latitude=18.7967,
            longitude=98.9667,
            location=Point(98.9667, 18.7967, srid=4326),
            is_open=True,
            bank_account_name='นายกาแฟ',
            bank_account_number='1234567890',
            bank_name='กสิกรไทย'
        )

        # สร้าง หมวดหมู่และเมนูอาหาร
        self.category = Category.objects.create(
            merchant=self.merchant_nimman,
            name='เครื่องดื่ม',
            sort_order=1
        )

        self.menu_item = MenuItem.objects.create(
            merchant=self.merchant_nimman,
            category=self.category,
            name='อเมริกาโน่เย็น',
            price=55.00,
            is_available=True
        )

        self.option = MenuOption.objects.create(
            menu_item=self.menu_item,
            name='หวานน้อย 50%',
            extra_price=0.00
        )

    def test_merchant_list_requires_location(self):
        """ไม่ส่งพิกัด → 400 LOCATION_REQUIRED (ไม่มีพิกัดกลางเมืองให้เดา — ใช้ได้หลายพื้นที่)"""
        url = reverse('merchant-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'LOCATION_REQUIRED')
        self.assertEqual(self.client.get(url + '?lat=18.78').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.get(url + '?lat=0&lng=0').status_code, status.HTTP_400_BAD_REQUEST)


    def test_merchant_list_with_valid_lat_lng(self):
        """ทดสอบส่งพิกัด lat/lng และคำนวณระยะทางด้วย PostGIS"""
        url = reverse('merchant-list') + '?lat=18.7883&lng=98.9853'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertGreaterEqual(len(response.data['data']), 1)
        self.assertIn('distance_km', response.data['data'][0])

    def test_get_merchant_menu(self):
        """ทดสอบดึงเมนูอาหารของร้านค้าแบบ Hierarchy"""
        url = reverse('merchant-menu', kwargs={'merchant_id': self.merchant_nimman.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['merchant_name'], 'ร้านกาแฟ นิมมาน')

    def test_toggle_store_status(self):
        """ทดสอบสลับสถานะเปิด/ปิดร้านค้า"""
        url = reverse('merchant-store-status')
        self.client.force_authenticate(user=self.merchant_user)

        response = self.client.patch(url, {'is_open': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['data']['is_open'])

        # ตรวจสอบการบันทึกลง DB
        self.merchant_nimman.refresh_from_db()
        self.assertFalse(self.merchant_nimman.is_open)

    def test_toggle_menu_item_availability(self):
        """ทดสอบสลับสถานะสินค้าหมด/มีจำหน่าย"""
        url = reverse('merchant-menu-toggle', kwargs={'item_id': self.menu_item.id})
        self.client.force_authenticate(user=self.merchant_user)

        response = self.client.patch(url, {'is_available': False}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['data']['is_available'])

        self.menu_item.refresh_from_db()
        self.assertFalse(self.menu_item.is_available)


class MerchantSearchSafetyTests(TestCase):
    """[P0-12] ค้นหาร้าน: ต้องไม่เขียน DB, ไม่คืนทั้งประเทศ, clamp radius"""

    def setUp(self):
        self.client = APIClient()
        self.merchant_user = User.objects.create(display_name='Merchant Owner', role=UserRole.MERCHANT)
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านใกล้',
            image_url='https://example.com/near.jpg',
            phone_number='0812345678',
            address='ถนนนิมมาน',
            latitude=18.7967,
            longitude=98.9667,
            location=Point(98.9667, 18.7967, srid=4326),
            is_open=True,
            bank_account_name='นายร้าน',
            bank_account_number='1234567890',
            bank_name='กสิกรไทย',
        )
        # ร้านปิด (ต้องไม่ถูกค้นเจอ)
        self.closed_merchant = Merchant.objects.create(
            user=User.objects.create(display_name='Closed Owner', role=UserRole.MERCHANT),
            name='ร้านปิด',
            image_url='',
            phone_number='0899999999',
            address='ถนนนิมมาน',
            latitude=18.7968,
            longitude=98.9668,
            location=Point(98.9668, 18.7968, srid=4326),
            is_open=False,
            bank_account_name='นายปิด',
            bank_account_number='0987654321',
            bank_name='กสิกรไทย',
        )

    def test_search_filters_closed_merchants(self):
        url = reverse('merchant-list') + '?lat=18.7883&lng=98.9853&radius=15'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        names = [row['name'] for row in response.data['data']]
        self.assertEqual(names, ['ร้านใกล้'])

    def test_search_outside_radius_returns_empty_without_fallback(self):
        """พิกัดกรุงเทพฯ ไกลจากเชียงใหม่ → ต้องได้ list ว่าง ไม่ใช่ร้านทั้งประเทศ"""
        url = reverse('merchant-list') + '?lat=13.7563&lng=100.5018&radius=1'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'], [])
        self.assertEqual(response.data['meta']['total'], 0)

    def test_search_radius_is_clamped_to_max(self):
        url = reverse('merchant-list') + '?lat=18.7883&lng=98.9853&radius=9999'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(
            response.data['meta']['radius_km'],
            response.data['meta']['max_radius_km'],
        )

    def test_search_rejects_invalid_radius(self):
        url = reverse('merchant-list') + '?lat=18.7883&lng=98.9853&radius=abc'
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])

    def test_search_is_read_only(self):
        """GET ต้องไม่สร้าง/แก้ข้อมูลร้านค้า (ไม่มี sync side-effect)"""
        url = reverse('merchant-list') + '?lat=18.7883&lng=98.9853&radius=15'
        before = Merchant.objects.count()

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Merchant.objects.count(), before)
        write_queries = [
            q['sql'] for q in ctx.captured_queries
            if q['sql'].lstrip().lower().startswith(('insert', 'update', 'delete'))
        ]
        self.assertEqual(write_queries, [])



class MenuItemDeleteTests(TestCase):
    """[P0-13] ลบเมนู: ถ้ามีประวัติการสั่งซื้อให้ซ่อนแทนการลบ (RESTRICT)"""

    def setUp(self):
        self.client = APIClient()
        self.merchant_user = User.objects.create(display_name='Merchant Owner', role=UserRole.MERCHANT)
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านทดสอบ',
            image_url='',
            phone_number='0812345678',
            address='นิมมาน',
            latitude=18.7967,
            longitude=98.9667,
            location=Point(98.9667, 18.7967, srid=4326),
            is_open=True,
            bank_account_name='นายร้าน',
            bank_account_number='1234567890',
            bank_name='กสิกรไทย',
        )
        self.used_item = MenuItem.objects.create(
            merchant=self.merchant, name='เมนูที่มีประวัติ', price=Decimal('50.00'), is_available=True
        )
        self.unused_item = MenuItem.objects.create(
            merchant=self.merchant, name='เมนูใหม่', price=Decimal('40.00'), is_available=True
        )
        other_user = User.objects.create(display_name='Other Owner', role=UserRole.MERCHANT)
        self.other_merchant = Merchant.objects.create(
            user=other_user,
            name='ร้านอื่น',
            image_url='',
            phone_number='0899999999',
            address='นิมมาน',
            latitude=18.7968,
            longitude=98.9668,
            location=Point(98.9668, 18.7968, srid=4326),
            is_open=True,
            bank_account_name='นายอื่น',
            bank_account_number='0987654321',
            bank_name='กสิกรไทย',
        )

    def _create_order_with_item(self):
        from apps.orders.models import Order, OrderItem, OrderStatus

        customer = User.objects.create(display_name='ลูกค้า', email='buyer@example.com', role=UserRole.CUSTOMER)
        order = Order.objects.create(
            order_number='ORD-DEL-0001',
            customer=customer,
            merchant=self.merchant,
            status=OrderStatus.COMPLETED,
            subtotal=Decimal('50.00'),
            delivery_fee=Decimal('30.00'),
            total_amount=Decimal('80.00'),
            delivery_address='nimman',
            delivery_latitude=Decimal('18.7967'),
            delivery_longitude=Decimal('98.9667'),
            delivery_distance_km=Decimal('1.00'),
            rider_delivery_fee=Decimal('25.00'),
            platform_fee=Decimal('2.50'),
            platform_delivery_fee=Decimal('5.00'),
        )
        OrderItem.objects.create(
            order=order,
            menu_item=self.used_item,
            item_name=self.used_item.name,
            unit_price=Decimal('50.00'),
            quantity=1,
            total_price=Decimal('50.00'),
        )
        return order

    def test_delete_used_item_soft_deletes(self):
        self._create_order_with_item()
        self.client.force_authenticate(user=self.merchant_user)
        url = reverse('merchant-menu-detail', kwargs={'item_id': self.used_item.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('ซ่อน', response.data['message'])
        self.used_item.refresh_from_db()
        self.assertFalse(self.used_item.is_available)
        self.assertTrue(MenuItem.objects.filter(id=self.used_item.id).exists())

    def test_delete_unused_item_hard_deletes(self):
        self.client.force_authenticate(user=self.merchant_user)
        url = reverse('merchant-menu-detail', kwargs={'item_id': self.unused_item.id})

        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(MenuItem.objects.filter(id=self.unused_item.id).exists())

    def test_cannot_delete_other_merchant_item(self):
        self.client.force_authenticate(user=self.other_merchant.user)
        url = reverse('merchant-menu-detail', kwargs={'item_id': self.unused_item.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)



class PublicMediaRegexTests(TestCase):
    """P0-11 ทาง A: เปิดเฉพาะรูปเมนู/รูปหน้าร้าน ส่วนไฟล์ส่วนตัวต้องไม่ match"""

    def setUp(self):
        import re
        from django.conf import settings
        from config.media_urls import build_public_media_regex
        self.pattern = re.compile(build_public_media_regex(settings.PUBLIC_MEDIA_PREFIXES))

    def test_public_folders_are_served(self):
        self.assertTrue(self.pattern.match('media/merchant-menus/pad-thai.jpg'))
        self.assertTrue(self.pattern.match('media/merchant-applications/storefronts/shop.png'))

    def test_private_folders_are_not_served(self):
        for path in [
            'media/delivery-proofs/images/a.jpg',
            'media/delivery-proofs/signatures/a.png',
            'media/payment-slips/x/slip.jpg',
            'media/merchant-applications/identity/id.jpg',
            'media/merchant-applications/documents/doc.pdf',
            'media/rider-applications/licenses/l.jpg',
        ]:
            self.assertIsNone(self.pattern.match(path), path)

    def test_path_traversal_blocked(self):
        self.assertIsNone(self.pattern.match('media/merchant-menus/../delivery-proofs/images/a.jpg'))


TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='fd-test-media-')


def _png_upload(name='shop.png'):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (234, 88, 12)).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
@mock.patch.dict(os.environ, {'BANK_DATA_ENCRYPTION_KEY': Fernet.generate_key().decode()})
class MerchantProfileTests(TestCase):
    """module_32 เฟส A: ร้านแก้ข้อมูลร้านเอง + บัญชีธนาคารต้องรอแอดมินอนุมัติ"""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create(display_name='Owner', email='owner@example.com', role=UserRole.MERCHANT)
        self.merchant = Merchant.objects.create(
            user=self.owner, name='ร้านเดิม', image_url='', phone_number='0812345678', address='ที่อยู่เดิม',
            latitude=12.9236, longitude=100.8825, location=Point(100.8825, 12.9236, srid=4326), is_open=True,
            bank_account_name='นายเดิม', bank_account_number='1234567890', bank_name='กสิกรไทย',
        )
        self.admin = User.objects.create(display_name='Admin', email='admin@example.com', role=UserRole.ADMIN, is_staff=True)
        self.client.force_authenticate(self.owner)
        self.url = reverse('merchant-profile')
        self.bank_url = reverse('merchant-bank-change')

    def test_get_profile_masks_account_number(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['bank']['account_number_masked'], '******7890')
        self.assertNotIn('1234567890', str(response.data))

    def test_patch_updates_info_and_location(self):
        response = self.client.patch(self.url, {'name': 'ร้านใหม่', 'address': 'ที่อยู่ใหม่', 'latitude': 12.95, 'longitude': 100.89}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.name, 'ร้านใหม่')
        self.assertEqual(self.merchant.address, 'ที่อยู่ใหม่')
        self.assertAlmostEqual(self.merchant.location.y, 12.95)
        self.assertAlmostEqual(self.merchant.location.x, 100.89)

    def test_patch_rejects_half_or_zero_location(self):
        self.assertEqual(self.client.patch(self.url, {'latitude': 12.9}, format='json').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.patch(self.url, {'latitude': 0, 'longitude': 0}, format='json').status_code, status.HTTP_400_BAD_REQUEST)
        self.merchant.refresh_from_db()
        self.assertAlmostEqual(float(self.merchant.latitude), 12.9236)

    def test_patch_cannot_change_bank_directly(self):
        self.client.patch(self.url, {'bank_account_number': '9999999999'}, format='json')
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.bank_account_number, '1234567890')

    def test_upload_store_image(self):
        response = self.client.patch(self.url, {'image': _png_upload()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.merchant.refresh_from_db()
        self.assertIn('/merchant-storefronts/', self.merchant.image_url)

    def test_reject_fake_image(self):
        fake = SimpleUploadedFile('shop.png', b'not an image', content_type='image/png')
        response = self.client.patch(self.url, {'image': fake}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_merchant_forbidden(self):
        self.client.force_authenticate(User.objects.create(display_name='C', email='c@example.com', role=UserRole.CUSTOMER))
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)

    def test_bank_change_waits_for_admin(self):
        response = self.client.post(self.bank_url, {'bank_name': 'ไทยพาณิชย์', 'bank_account_name': 'นายใหม่', 'bank_account_number': '987-6-54321-0'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.bank_account_number, '1234567890')  # ยังเป็นบัญชีเดิม
        change = MerchantBankChangeRequest.objects.get(merchant=self.merchant)
        self.assertEqual(change.status, BankChangeStatus.PENDING)
        self.assertNotIn('9876543210', change.bank_account_number_encrypted)  # เก็บแบบเข้ารหัส

    def test_new_request_cancels_previous_pending(self):
        payload = {'bank_name': 'ไทยพาณิชย์', 'bank_account_name': 'นายใหม่', 'bank_account_number': '9876543210'}
        self.client.post(self.bank_url, payload, format='json')
        self.client.post(self.bank_url, {**payload, 'bank_account_number': '1111222233'}, format='json')
        statuses = list(MerchantBankChangeRequest.objects.order_by('created_at').values_list('status', flat=True))
        self.assertEqual(statuses, [BankChangeStatus.CANCELLED, BankChangeStatus.PENDING])

    def test_invalid_account_number(self):
        response = self.client.post(self.bank_url, {'bank_name': 'x', 'bank_account_name': 'y', 'bank_account_number': '12ab'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_approve_applies_new_account(self):
        self.client.post(self.bank_url, {'bank_name': 'ไทยพาณิชย์', 'bank_account_name': 'นายใหม่', 'bank_account_number': '9876543210'}, format='json')
        change = MerchantBankChangeRequest.objects.get()
        approve_bank_change(change.id, self.admin)
        self.merchant.refresh_from_db()
        change.refresh_from_db()
        self.assertEqual(self.merchant.bank_account_number, '9876543210')
        self.assertEqual(self.merchant.bank_name, 'ไทยพาณิชย์')
        self.assertEqual(change.status, BankChangeStatus.APPROVED)
        self.assertEqual(change.reviewer, self.admin)
        with self.assertRaises(BankChangeError):
            approve_bank_change(change.id, self.admin)  # ตรวจซ้ำไม่ได้

    def test_reject_keeps_old_account_and_needs_reason(self):
        self.client.post(self.bank_url, {'bank_name': 'ไทยพาณิชย์', 'bank_account_name': 'นายใหม่', 'bank_account_number': '9876543210'}, format='json')
        change = MerchantBankChangeRequest.objects.get()
        with self.assertRaises(BankChangeError):
            reject_bank_change(change.id, self.admin, reason='สั้น')
        reject_bank_change(change.id, self.admin, reason='ชื่อบัญชีไม่ตรงกับเจ้าของร้าน')
        self.merchant.refresh_from_db()
        self.assertEqual(self.merchant.bank_account_number, '1234567890')
        response = self.client.get(self.url)
        self.assertEqual(response.data['data']['bank_change']['status'], BankChangeStatus.REJECTED)
