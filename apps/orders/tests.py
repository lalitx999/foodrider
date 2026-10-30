from decimal import Decimal
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import User, UserRole, CustomerProfile
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.payments.models import SlipStatus, SlipTransaction


class OrderApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # สร้าง User ลูกค้าและร้านค้า
        self.customer = User.objects.create(
            display_name='Somchai Customer',
            email='customer@example.com',
            role=UserRole.CUSTOMER
        )
        self.customer_profile = CustomerProfile.objects.create(
            user=self.customer,
            default_delivery_address='ถนนนิมมาน เชียงใหม่'
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
            slip_image_url='/media/payment-slips/old.png',
            is_verified=True,
            status=SlipStatus.APPROVED,
            attempt_no=1,
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
        with self.settings(PAYMENT_VERIFICATION_MODE='API'), \
                patch('apps.payments.services.call_slip_verify_api') as mock_api:
            # จำลอง API ส่ง trans_ref ที่ถูกใช้ไปแล้ว
            mock_api.return_value = {
                'is_success': True,
                'trans_ref': 'USED_REF_12345',
                'amount': '70.00',
                'receiving_account': '0810000000',
                'raw_payload': {}
            }

            response = self.client.post(
                url, {'slip_image': self._slip_file()}, format='multipart'
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(response.data['success'])
            self.assertIn('Double Spending Detected', response.data['message'])

    def _slip_file(self):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buffer = BytesIO()
        Image.new('RGB', (8, 8), color='white').save(buffer, format='PNG')
        return SimpleUploadedFile('slip.png', buffer.getvalue(), content_type='image/png')


class MerchantOrderListTests(TestCase):
    """P0-04: ร้านต้องไม่เห็นออเดอร์ที่ยังไม่จ่าย + รองรับ ?status= / ?since="""

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(
            display_name='ลูกค้า KDS', email='kds-customer@example.com', role=UserRole.CUSTOMER
        )
        CustomerProfile.objects.create(user=self.customer, default_delivery_address='ที่อยู่ทดสอบ')
        self.merchant_user = User.objects.create(
            display_name='ร้าน KDS', email='kds-merchant@example.com', role=UserRole.MERCHANT
        )
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้าน KDS ทดสอบ',
            image_url='https://example.com/kds.png',
            phone_number='0888888888',
            address='ถนนทดสอบ',
            latitude=Decimal('18.7883'),
            longitude=Decimal('98.9853'),
            location=Point(98.9853, 18.7883, srid=4326),
            is_open=True,
            bank_account_name='ร้าน KDS',
            bank_account_number='0000000000',
            bank_name='กสิกรไทย',
        )
        self.unpaid = self._order('ORD-KDS-UNPAID', OrderStatus.PENDING_PAYMENT)
        self.paid = self._order('ORD-KDS-PAID', OrderStatus.PAID)
        self.preparing = self._order('ORD-KDS-PREPARING', OrderStatus.PREPARING)
        self.client.force_authenticate(user=self.merchant_user)

    def _order(self, order_number, order_status):
        return Order.objects.create(
            order_number=order_number,
            customer=self.customer,
            merchant=self.merchant,
            status=order_status,
            subtotal=Decimal('100.00'),
            delivery_fee=Decimal('30.00'),
            total_amount=Decimal('130.00'),
            delivery_address='ที่อยู่จัดส่ง',
            delivery_latitude=Decimal('18.7900'),
            delivery_longitude=Decimal('98.9860'),
            delivery_distance_km=Decimal('1.00'),
            rider_delivery_fee=Decimal('25.00'),
            platform_fee=Decimal('10.00'),
        )

    @property
    def list_url(self):
        return reverse('merchant-orders')

    def _statuses(self, response):
        return {row['status'] for row in response.data['data']}

    def test_merchant_order_list_excludes_unpaid(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {row['id'] for row in response.data['data']}
        self.assertNotIn(str(self.unpaid.id), returned_ids)
        self.assertIn(str(self.paid.id), returned_ids)
        self.assertIn(str(self.preparing.id), returned_ids)

    def test_status_filter(self):
        response = self.client.get(self.list_url, {'status': OrderStatus.PREPARING})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._statuses(response), {OrderStatus.PREPARING})

    def test_since_filter(self):
        response = self.client.get(
            self.list_url, {'since': self.preparing.updated_at.isoformat()}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {row['id'] for row in response.data['data']}
        self.assertNotIn(str(self.unpaid.id), returned_ids)
        self.assertNotIn(str(self.paid.id), returned_ids)
        self.assertEqual(returned_ids, {str(self.preparing.id)})

    def test_unknown_status_rejected(self):
        response = self.client.get(self.list_url, {'status': 'NOT_A_STATUS'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'INVALID_QUERY_PARAM')

    def test_bad_since_rejected(self):
        response = self.client.get(self.list_url, {'since': 'yesterday'})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'INVALID_QUERY_PARAM')

    def test_list_query_count_under_limit(self):
        menu_item = MenuItem.objects.create(
            merchant=self.merchant, name='ส้มตำ KDS', price=Decimal('100.00'), is_available=True
        )
        OrderItem.objects.create(
            order=self.paid,
            menu_item=menu_item,
            item_name='ส้มตำ',
            unit_price=Decimal('100.00'),
            quantity=1,
            total_price=Decimal('100.00'),
        )
        SlipTransaction.objects.create(
            order=self.paid,
            trans_ref='KDS-SLIP-0001',
            amount=self.paid.total_amount,
            slip_image_url='payment-slips/test/kds.png',
            status=SlipStatus.APPROVED,
            attempt_no=1,
        )

        # AC P0-04: จำนวน query ของ list ≤ 5 แม้มี items/slips หลายรายการ
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(queries), 5, [q['sql'] for q in queries])


class OrderPayloadValidationTests(TestCase):
    """P0-06: ตรวจพิกัด/จำนวน/ความยาวข้อความก่อนคำนวณเงิน"""

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(
            display_name='ลูกค้า Validate', email='validate@example.com', role=UserRole.CUSTOMER
        )
        CustomerProfile.objects.create(user=self.customer, default_delivery_address='ที่อยู่ทดสอบ')
        merchant_user = User.objects.create(
            display_name='ร้าน Validate', email='validate-merchant@example.com', role=UserRole.MERCHANT
        )
        self.merchant = Merchant.objects.create(
            user=merchant_user,
            name='ร้าน Validate',
            image_url='https://example.com/v.png',
            phone_number='0877777777',
            address='ถนนทดสอบ',
            latitude=Decimal('18.7883'),
            longitude=Decimal('98.9853'),
            location=Point(98.9853, 18.7883, srid=4326),
            is_open=True,
            bank_account_name='ร้าน Validate',
            bank_account_number='0000000000',
            bank_name='กสิกรไทย',
        )
        self.menu_item = MenuItem.objects.create(
            merchant=self.merchant, name='ข้าวผัด', price=Decimal('50.00'), is_available=True
        )
        self.client.force_authenticate(user=self.customer)

    def _payload(self, **overrides):
        payload = {
            'merchant_id': str(self.merchant.id),
            'delivery_lat': 18.79,
            'delivery_lng': 98.98,
            'delivery_address': 'ที่อยู่จัดส่ง',
            'items': [{'menu_item_id': str(self.menu_item.id), 'quantity': 1}],
        }
        payload.update(overrides)
        return payload

    def _post(self, **overrides):
        return self.client.post(
            reverse('order-create'), self._payload(**overrides), format='json'
        )

    def test_latitude_out_of_range(self):
        response = self._post(delivery_lat=91)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('delivery_lat', response.data['details'])

    def test_longitude_out_of_range(self):
        response = self._post(delivery_lng=-181)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('delivery_lng', response.data['details'])

    def test_quantity_over_limit(self):
        response = self._post(
            items=[{'menu_item_id': str(self.menu_item.id), 'quantity': 21}]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_too_many_items(self):
        response = self._post(
            items=[{'menu_item_id': str(self.menu_item.id), 'quantity': 1} for _ in range(31)]
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_note_too_long(self):
        response = self._post(note_to_merchant='ก' * 501)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_address_too_long(self):
        response = self._post(delivery_address='ก' * 501)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    DELIVERY_BASE_FARE=Decimal('30.00'),
    DELIVERY_BASE_DISTANCE_KM=Decimal('3.00'),
    DELIVERY_PER_KM_FARE=Decimal('6.00'),
    RIDER_BASE_EARNING=Decimal('25.00'),
    RIDER_PER_KM_EARNING=Decimal('5.00'),
)
class DeliveryFeeBr7Tests(TestCase):
    """BR-7: ตารางค่าจัดส่ง 6 เคสต้องได้เป๊ะ (P0-15)"""

    CASES = [
        # (distance_km, extra_km, delivery_fee, rider_fee, platform_delivery_fee)
        ('1.00', 0, '30.00', '25.00', '5.00'),
        ('3.00', 0, '30.00', '25.00', '5.00'),
        ('3.01', 1, '36.00', '30.00', '6.00'),
        ('5.40', 3, '48.00', '40.00', '8.00'),
        ('8.00', 5, '60.00', '50.00', '10.00'),
        ('15.00', 12, '102.00', '85.00', '17.00'),
    ]

    def test_br7_table(self):
        from apps.orders.services import compute_delivery_fee

        for distance, extra_km, delivery_fee, rider_fee, platform_fee in self.CASES:
            with self.subTest(distance_km=distance):
                result = compute_delivery_fee(Decimal(distance))
                self.assertEqual(result['extra_km'], extra_km)
                self.assertEqual(result['delivery_fee'], Decimal(delivery_fee))
                self.assertEqual(result['rider_fee'], Decimal(rider_fee))
                self.assertEqual(result['platform_delivery_fee'], Decimal(platform_fee))
                # invariant บังคับ: ลูกค้าจ่าย = ไรเดอร์ได้ + แพลตฟอร์มได้
                self.assertEqual(
                    result['delivery_fee'],
                    result['rider_fee'] + result['platform_delivery_fee'],
                )

