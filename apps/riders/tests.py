from decimal import Decimal
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

        response = self.client.post(url, {
            'proof_image_url': 'https://example.com/delivery_proof.jpg'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])

        # ตรวจสอบยอดเงินในกระเป๋าไรเดอร์เพิ่มขึ้น 25.50 บาท
        self.rider_profile_1.refresh_from_db()
        self.assertEqual(self.rider_profile_1.wallet_balance, Decimal('25.50'))
