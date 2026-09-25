from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import User, UserRole
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.payments.models import SlipTransaction


class OrderApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # สร้าง User ลูกค้าและร้านค้า
        self.customer = User.objects.create(
            display_name='Somchai Customer',
            email='customer@example.com',
            role=UserRole.CUSTOMER
        )
        self.merchant_user = User.objects.create(
            display_name='Somsee Merchant',
            role=UserRole.MERCHANT
        )

        # ร้านค้า (นิมมาน)
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านส้มตำ ป้าสมศรี',
            image_url='https://example.com/somtam.jpg',
            phone_number='0899999999',
            address='ถนนสุเทพ',
            latitude=18.7883,
            longitude=98.9853,
            location=Point(98.9853, 18.7883, srid=4326),
            is_open=True,
            bank_account_name='สมศรี ใจดี',
            bank_account_number='0810000000',
            bank_name='กสิกรไทย'
        )

        # เมนูอาหาร
        self.menu_item = MenuItem.objects.create(
            merchant=self.merchant,
            name='ส้มตำไทย',
            price=Decimal('50.00'),
            is_available=True
        )

        self.option = MenuOption.objects.create(
            menu_item=self.menu_item,
            name='เผ็ดน้อย',
            extra_price=Decimal('0.00')
        )

    def test_order_quote_calculation(self):
        """ทดสอบคำนวณยอดเงินและค่าส่ง Order Quote บน Backend"""
        url = reverse('order-quote')
        payload = {
            'merchant_id': str(self.merchant.id),
            'delivery_lat': 18.7900,
            'delivery_lng': 98.9860,
            'items': [{
                'menu_item_id': str(self.menu_item.id),
                'quantity': 2,
                'option_ids': [str(self.option.id)]
            }]
        }

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        # ค่าอาหาร 50 * 2 = 100 บาท
        self.assertEqual(Decimal(str(response.data['data']['subtotal'])), Decimal('100.00'))

    def test_create_order_atomic(self):
        """ทดสอบการสร้าง Order พร้อม Snapshot ข้อมูล OrderItem"""
        url = reverse('order-create')
        self.client.force_authenticate(user=self.customer)

        payload = {
            'merchant_id': str(self.merchant.id),
            'delivery_lat': 18.7900,
            'delivery_lng': 98.9860,
            'delivery_address': 'คอนโด นิมมาน ชั้น 5',
            'note_to_merchant': 'ช้อนส้อมด้วยครับ',
            'items': [{
                'menu_item_id': str(self.menu_item.id),
                'quantity': 1,
                'option_ids': [str(self.option.id)]
            }]
        }

        response = self.client.post(url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['status'], 'PENDING_PAYMENT')

        # ตรวจสอบ Snapshot ใน OrderItem
        order_id = response.data['data']['id']
        order_item = OrderItem.objects.get(order_id=order_id)
        self.assertEqual(order_item.item_name, 'ส้มตำไทย')
        self.assertEqual(order_item.unit_price, Decimal('50.00'))

    def test_anti_fraud_double_spending_slip(self):
        """ทดสอบการตรวจจับสลิปซ้ำ (Double Spending Prevention)"""
        # สร้าง Order และ SlipTransaction ที่เคยใช้งานไปแล้ว
        order1 = Order.objects.create(
            order_number='ORD-TEST-1',
            customer=self.customer,
            merchant=self.merchant,
            status=OrderStatus.PAID,
            subtotal=Decimal('50.00'),
            delivery_fee=Decimal('20.00'),
            total_amount=Decimal('70.00'),
            delivery_address='ที่อยู่เดิม',
            delivery_latitude=18.78,
            delivery_longitude=98.98,
            delivery_distance_km=Decimal('1.0'),
            rider_delivery_fee=Decimal('17.00'),
            platform_fee=Decimal('7.50')
        )

        SlipTransaction.objects.create(
            order=order1,
            trans_ref='USED_REF_12345',
            amount=Decimal('70.00'),
            slip_image_url='https://example.com/slip.jpg',
            is_verified=True
        )

        # สร้าง Order ใหม่เพื่อลองส่งสลิปซ้ำ
        order2 = Order.objects.create(
            order_number='ORD-TEST-2',
            customer=self.customer,
            merchant=self.merchant,
            status=OrderStatus.PENDING_PAYMENT,
            subtotal=Decimal('50.00'),
            delivery_fee=Decimal('20.00'),
            total_amount=Decimal('70.00'),
            delivery_address='ที่อยู่ใหม่',
            delivery_latitude=18.78,
            delivery_longitude=98.98,
            delivery_distance_km=Decimal('1.0'),
            rider_delivery_fee=Decimal('17.00'),
            platform_fee=Decimal('7.50')
        )

        url = reverse('order-upload-slip', kwargs={'order_id': order2.id})
        self.client.force_authenticate(user=self.customer)

        from unittest.mock import patch
        with patch('apps.payments.services.call_slip_verify_api') as mock_api:
            # จำลอง API ส่ง trans_ref ที่ถูกใช้ไปแล้ว
            mock_api.return_value = {
                'is_success': True,
                'trans_ref': 'USED_REF_12345',
                'amount': '70.00',
                'receiving_account': '0810000000',
                'raw_payload': {}
            }

            from io import BytesIO
            fake_file = BytesIO(b"fake image content")
            fake_file.name = 'slip.jpg'

            response = self.client.post(url, {'slip_image': fake_file}, format='multipart')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(response.data['success'])
            self.assertIn('Double Spending Detected', response.data['message'])
