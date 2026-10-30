import io
from decimal import Decimal
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import User, UserRole
from apps.merchants.models import Merchant
from apps.orders.models import Order, OrderStatus
from apps.riders.models import RiderProfile


class RiderApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # สร้าง Users
        self.customer = User.objects.create(display_name='Customer 1', role=UserRole.CUSTOMER)
        self.merchant_user = User.objects.create(display_name='Merchant 1', role=UserRole.MERCHANT)
        self.rider_user_1 = User.objects.create(display_name='Rider 1', role=UserRole.RIDER)
        self.rider_user_2 = User.objects.create(display_name='Rider 2', role=UserRole.RIDER)

        # โปรไฟล์ไรเดอร์
        self.rider_profile_1 = RiderProfile.objects.create(
            user=self.rider_user_1,
            vehicle_plate='1กข-9999',
            is_online=True,
            wallet_balance=Decimal('0.00')
        )
        self.rider_profile_2 = RiderProfile.objects.create(
            user=self.rider_user_2,
            vehicle_plate='2กข-8888',
            is_online=True,
            wallet_balance=Decimal('0.00')
        )

        # ร้านค้า
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านข้าวมันไก่ นิมมาน',
            image_url='https://example.com/chicken.jpg',
            phone_number='0811111111',
            address='นิมมาน',
            latitude=18.7883,
            longitude=98.9853,
            location=Point(98.9853, 18.7883, srid=4326),
            is_open=True,
            bank_account_name='ไก่ดี',
            bank_account_number='0811111111',
            bank_name='กรุงไทย'
        )

        # สร้าง ออเดอร์ที่พร้อมให้ไรเดอร์รับงาน (READY_FOR_PICKUP)
        self.order = Order.objects.create(
            order_number='ORD-RIDER-TEST-1',
            customer=self.customer,
            merchant=self.merchant,
            status=OrderStatus.READY_FOR_PICKUP,
            subtotal=Decimal('100.00'),
            delivery_fee=Decimal('30.00'),
            total_amount=Decimal('130.00'),
            delivery_address='บ้านเลขที่ 123',
            delivery_latitude=18.7900,
            delivery_longitude=98.9860,
            delivery_distance_km=Decimal('2.0'),
            rider_delivery_fee=Decimal('25.50'),
            platform_fee=Decimal('15.00')
        )

    def test_rider_toggle_status(self):
        """ทดสอบเปิด/ปิดสถานะรับงานของไรเดอร์"""
        url = reverse('rider-status')
        self.client.force_authenticate(user=self.rider_user_1)

        response = self.client.patch(url, {
            'is_online': True,
            'current_lat': 18.7890,
            'current_lng': 98.9855
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertTrue(response.data['data']['is_online'])

    def test_available_jobs_list(self):
        """ทดสอบดึงรายการงานว่างที่พร้อมรับ"""
        url = reverse('rider-jobs-available')
        self.client.force_authenticate(user=self.rider_user_1)

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(len(response.data['data']), 1)

    def test_claim_job_concurrency_race_prevention(self):
        """ทดสอบการกดรับงาน และป้องกันไม่ให้ไรเดอร์คนที่ 2 รับงานซ้ำได้ (Row Lock test)"""
        url = reverse('rider-job-claim', kwargs={'order_id': self.order.id})

        # ไรเดอร์คนแรกกดรับงาน
        self.client.force_authenticate(user=self.rider_user_1)
        response1 = self.client.post(url)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertTrue(response1.data['success'])

        # ไรเดอร์คนที่สองกดรับงานเดียวกัน
        self.client.force_authenticate(user=self.rider_user_2)
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, status.HTTP_409_CONFLICT)
        self.assertFalse(response2.data['success'])
        self.assertEqual(response2.data['error_code'], 'JOB_ALREADY_CLAIMED')

    def test_complete_job_earns_wallet_balance(self):
        """ทดสอบปิดงานจัดส่งสำเร็จและเติมเงินเข้า wallet_balance ของไรเดอร์"""
        # ไรเดอร์รับงานแล้ว
        self.order.rider = self.rider_user_1
        self.order.status = OrderStatus.DELIVERING
        self.order.save()

        url = reverse('rider-job-complete', kwargs={'order_id': self.order.id})
        self.client.force_authenticate(user=self.rider_user_1)

        proof_io = io.BytesIO()
        Image.new('RGB', (10, 10), color='green').save(proof_io, 'JPEG')
        proof_io.seek(0)
        proof_file = SimpleUploadedFile('proof.jpg', proof_io.read(), content_type='image/jpeg')

        sig_io = io.BytesIO()
        Image.new('RGB', (10, 10), color='black').save(sig_io, 'JPEG')
        sig_io.seek(0)
        sig_file = SimpleUploadedFile('sig.jpg', sig_io.read(), content_type='image/jpeg')

        response = self.client.post(url, {
            'proof_image': proof_file,
            'signature_image': sig_file,
            'recipient_confirmed': True,
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])

        # ตรวจสอบยอดเงินในกระเป๋าไรเดอร์เพิ่มขึ้น 25.50 บาท
        self.rider_profile_1.refresh_from_db()
        self.assertEqual(self.rider_profile_1.wallet_balance, Decimal('25.50'))


class RiderActiveJobTests(TestCase):
    """[P0-16] งานที่กำลังส่ง + ลิงก์นำทางที่พิกัดถูกต้อง"""

    def setUp(self):
        self.client = APIClient()
        self.customer = User.objects.create(display_name='Customer Active', role=UserRole.CUSTOMER)
        self.merchant_user = User.objects.create(display_name='Merchant Active', role=UserRole.MERCHANT)
        self.rider_user = User.objects.create(display_name='Rider Active', role=UserRole.RIDER)
        self.other_rider = User.objects.create(display_name='Rider Other', role=UserRole.RIDER)
        RiderProfile.objects.create(user=self.rider_user, vehicle_plate='3กข-7777', is_online=True)
        RiderProfile.objects.create(user=self.other_rider, vehicle_plate='4กข-6666', is_online=True)

        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านทดสอบไรเดอร์',
            image_url='',
            phone_number='0812222222',
            address='นิมมาน ซอย 9',
            latitude=Decimal('18.7883'),
            longitude=Decimal('98.9853'),
            location=Point(98.9853, 18.7883, srid=4326),
            is_open=True,
            bank_account_name='ร้านทดสอบ',
            bank_account_number='0812222222',
            bank_name='กรุงไทย',
        )

        self.order = Order.objects.create(
            order_number='ORD-RIDER-ACTIVE-1',
            customer=self.customer,
            merchant=self.merchant,
            rider=self.rider_user,
            status=OrderStatus.DELIVERING,
            subtotal=Decimal('100.00'),
            delivery_fee=Decimal('36.00'),
            total_amount=Decimal('136.00'),
            delivery_address='บ้านเลขที่ 99',
            delivery_latitude=Decimal('18.7900'),
            delivery_longitude=Decimal('98.9860'),
            delivery_distance_km=Decimal('3.40'),
            rider_delivery_fee=Decimal('30.00'),
            platform_fee=Decimal('15.00'),
            platform_delivery_fee=Decimal('6.00'),
        )

    def test_active_job_returned(self):
        self.client.force_authenticate(user=self.rider_user)
        response = self.client.get(reverse('rider-job-active'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['data']['has_active_job'])
        order_data = response.data['data']['order']
        self.assertEqual(order_data['order_number'], 'ORD-RIDER-ACTIVE-1')
        self.assertEqual(order_data['estimated_time'], '11 นาที')
        self.assertEqual(order_data['cod_amount'], 136.0)
        self.assertEqual(order_data['rider_earning'], 30.0)
        self.assertEqual(order_data['merchant_lat'], 18.7883)
        self.assertEqual(order_data['navigation']['to_customer']['lat'], 18.79)
        self.assertIsNotNone(order_data['navigation']['to_customer']['google_maps_url'])

    def test_no_active_job_returns_null(self):
        self.client.force_authenticate(user=self.other_rider)
        response = self.client.get(reverse('rider-job-active'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['data']['has_active_job'])
        self.assertIsNone(response.data['data']['order'])

    def test_navigation_url_includes_origin(self):
        self.client.force_authenticate(user=self.rider_user)
        url = reverse('rider-job-active') + '?lat=18.7880&lng=98.9850'
        response = self.client.get(url)

        navigation_url = response.data['data']['order']['navigation']['to_store']['google_maps_url']
        self.assertIn('origin=18.788,98.985', navigation_url)
        self.assertIn('destination=18.7883,98.9853', navigation_url)
        self.assertIn('travelmode=driving', navigation_url)

    def test_missing_coords_return_null(self):
        # ข้อมูลพิกัดหายมักถูกบันทึกเป็น 0,0 → ต้องคืน null ไม่ใช่ลิงก์อ่าวกินี
        self.merchant.latitude = Decimal('0')
        self.merchant.longitude = Decimal('0')
        self.merchant.location = None
        self.merchant.save(update_fields=['latitude', 'longitude', 'location'])

        self.client.force_authenticate(user=self.rider_user)
        response = self.client.get(reverse('rider-job-active') + '?lat=0&lng=0')

        order_data = response.data['data']['order']
        self.assertIsNone(order_data['merchant_lat'])
        self.assertIsNone(order_data['merchant_lng'])
        to_store = order_data['navigation']['to_store']
        self.assertIsNone(to_store['lat'])
        self.assertIsNone(to_store['lng'])
        self.assertIsNone(to_store['google_maps_url'])
        # origin 0,0 ต้องไม่ถูกส่งไปใน URL ของจุดส่ง
        self.assertNotIn('origin=', order_data['navigation']['to_customer']['google_maps_url'])

    def test_google_maps_url_points_to_customer(self):
        self.client.force_authenticate(user=self.rider_user)
        response = self.client.get(reverse('rider-job-active'))
        maps_url = response.data['data']['order']['google_maps_url']
        self.assertIn('destination=18.79,98.986', maps_url)
        self.assertNotIn('18.7883', maps_url)

