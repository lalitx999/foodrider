from django.test import TestCase
from django.urls import reverse
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import User, UserRole
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


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

    def test_merchant_list_defaults_lat_lng(self):
        """ทดสอบไม่ส่งพิกัด lat/lng ระบบจะใช้ค่าเริ่มต้นของพิกัดพัทยาและตอบกลับ 200 OK"""
        url = reverse('merchant-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])


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
