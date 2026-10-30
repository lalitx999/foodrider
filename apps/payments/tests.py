import os
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from apps.merchants.models import Merchant
from apps.orders.models import Order, OrderStatus, OrderStatusLog
from apps.payments.models import SlipStatus, SlipTransaction
from apps.payments.storage import slip_storage
from apps.users.media_tokens import make_media_token
from apps.users.models import CustomerProfile, User, UserRole


def make_slip_image(name='slip.png'):
    """สร้างรูป PNG จริงเพื่อผ่านการตรวจ magic bytes (PIL)"""
    buffer = BytesIO()
    Image.new('RGB', (12, 12), color='white').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class BaseSlipTestCase(TestCase):
    def setUp(self):
        # ไฟล์สลิปต้องไม่ตกค้างใน repo (และไม่ปนกับข้อมูลจริง) — P0-05
        slip_dir = tempfile.mkdtemp(prefix='food-slip-test-')
        override = override_settings(SLIP_STORAGE_LOCATION=slip_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, slip_dir, True)

        cache.clear()  # กัน throttle สะสมข้าม test
        self.client = APIClient()
        self.customer = User.objects.create(
            display_name='ลูกค้า ทดสอบ', email='customer-slip@example.com', role=UserRole.CUSTOMER
        )
        CustomerProfile.objects.create(
            user=self.customer, default_delivery_address='ที่อยู่ทดสอบ'
        )
        self.merchant_user = User.objects.create(
            display_name='ร้าน ทดสอบ', email='merchant-slip@example.com', role=UserRole.MERCHANT
        )
        self.merchant = Merchant.objects.create(
            user=self.merchant_user,
            name='ร้านทดสอบสลิป',
            image_url='https://example.com/shop.png',
            phone_number='0899999999',
            address='ถนนทดสอบ',
            latitude=Decimal('18.7883'),
            longitude=Decimal('98.9853'),
            location=Point(98.9853, 18.7883, srid=4326),
            is_open=True,
            bank_account_name='ร้าน ทดสอบ',
            bank_account_number='0000000000',
            bank_name='กสิกรไทย',
        )
        self.admin = User.objects.create(
            display_name='แอดมิน', email='admin-slip@example.com', role=UserRole.ADMIN
        )
        self.order = self._create_order()

    def _create_order(self, order_number='ORD-SLIP-0001', order_status=OrderStatus.PENDING_PAYMENT):
        return Order.objects.create(
            order_number=order_number,
            customer=self.customer,
            merchant=self.merchant,
            status=order_status,
            subtotal=Decimal('200.00'),
            delivery_fee=Decimal('45.00'),
            total_amount=Decimal('245.00'),
            delivery_address='ที่อยู่จัดส่งทดสอบ',
            delivery_latitude=Decimal('18.7900'),
            delivery_longitude=Decimal('98.9860'),
            delivery_distance_km=Decimal('3.00'),
            rider_delivery_fee=Decimal('35.00'),
            platform_fee=Decimal('7.50'),
            platform_delivery_fee=Decimal('10.00'),
        )

    @property
    def upload_url(self):
        return reverse('order-upload-slip', kwargs={'order_id': self.order.id})

    def _upload_slip(self, user=None, slip_file=None):
        self.client.force_authenticate(user=user or self.customer)
        return self.client.post(
            self.upload_url,
            {'slip_image': slip_file or make_slip_image()},
            format='multipart',
        )

    def _make_pending_slip(self, trans_ref='MANUAL-TEST0001', attempt_no=1):
        return SlipTransaction.objects.create(
            order=self.order,
            trans_ref=trans_ref,
            amount=self.order.total_amount,
            slip_image_url='/media/payment-slips/test.png',
            status=SlipStatus.PENDING,
            attempt_no=attempt_no,
        )


class ManualModeTests(BaseSlipTestCase):
    """P0-01: โหมด MANUAL ต้องไม่ auto-approve และไม่แตะสถานะออเดอร์"""

    def test_slip_stays_pending(self):
        with patch('apps.payments.services.create_and_send_notification') as notify:
            with self.captureOnCommitCallbacks(execute=True):
                response = self._upload_slip()

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['slip_status'], SlipStatus.PENDING)
        self.assertEqual(response.data['data']['order_status'], OrderStatus.PENDING_PAYMENT)
        self.assertEqual(response.data['data']['attempt_no'], 1)
        self.assertTrue(notify.called, 'ต้องแจ้งเตือนแอดมินเมื่อมีสลิปใหม่')

    def test_no_auto_paid(self):
        with patch('apps.payments.services.create_and_send_notification'):
            self._upload_slip()

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)
        self.assertIsNone(self.order.paid_at)
        self.assertFalse(
            OrderStatusLog.objects.filter(order=self.order, to_status=OrderStatus.PAID).exists()
        )
        slip = SlipTransaction.objects.get(order=self.order)
        self.assertEqual(slip.status, SlipStatus.PENDING)
        self.assertFalse(slip.is_verified)
        self.assertTrue(slip.trans_ref.startswith('MANUAL-'))
        # ไฟล์เก็บนอก MEDIA_ROOT (P0-05) — เก็บเป็น relative name ใน private storage
        self.assertFalse(slip.slip_image_url.startswith('/media/'))
        self.assertFalse(os.path.isabs(slip.slip_image_url))
        self.assertTrue(slip.slip_image_url.startswith('payment-slips/'))
        self.assertTrue(slip_storage.exists(slip.slip_image_url))


class SlipFileEndpointTests(BaseSlipTestCase):
    """P0-05/P0-11: ไฟล์สลิปเข้าถึงได้เฉพาะ signed endpoint และ /media/ ต้องไม่ถูกเสิร์ฟ"""

    def _slip_with_file(self):
        buffer = BytesIO()
        Image.new('RGB', (10, 10), color='white').save(buffer, format='PNG')
        name = slip_storage.save('payment-slips/test/slip.png', ContentFile(buffer.getvalue()))
        return SlipTransaction.objects.create(
            order=self.order,
            trans_ref='FILE-TEST0001',
            amount=self.order.total_amount,
            slip_image_url=name,
            status=SlipStatus.PENDING,
            attempt_no=1,
        )

    def _file_url(self, slip, token=None):
        return reverse('media-slip', kwargs={
            'slip_id': slip.id,
            'token': token or make_media_token(slip.id),
        })

    def test_streams_file_with_valid_token(self):
        slip = self._slip_with_file()
        response = self.client.get(self._file_url(slip))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'image/png')
        content = b''.join(response.streaming_content)
        self.assertTrue(content.startswith(b'\x89PNG'))

    def test_x_accel_redirect_in_production(self):
        slip = self._slip_with_file()
        with override_settings(USE_X_ACCEL_REDIRECT=True, X_ACCEL_REDIRECT_PREFIX='/private-media/'):
            response = self.client.get(self._file_url(slip))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response['X-Accel-Redirect'],
            f"/private-media/{slip.slip_image_url}",
        )

    def test_expired_token_rejected(self):
        slip = self._slip_with_file()
        token = make_media_token(slip.id)
        with override_settings(SLIP_SIGNED_URL_TTL_SECONDS=-1):
            response = self.client.get(self._file_url(slip, token=token))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error_code'], 'MEDIA_TOKEN_EXPIRED')

    def test_tampered_token_rejected(self):
        slip = self._slip_with_file()
        response = self.client.get(self._file_url(slip, token='not-a-valid-token'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error_code'], 'MEDIA_TOKEN_INVALID')

    def test_token_for_other_slip_rejected(self):
        slip = self._slip_with_file()
        other = SlipTransaction.objects.create(
            order=self._create_order(order_number='ORD-SLIP-0002'),
            trans_ref='FILE-TEST0002',
            amount=self.order.total_amount,
            slip_image_url='payment-slips/test/other.png',
            status=SlipStatus.PENDING,
            attempt_no=1,
        )
        response = self.client.get(self._file_url(slip, token=make_media_token(other.id)))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['error_code'], 'MEDIA_TOKEN_INVALID')

    def test_public_media_path_not_served(self):
        slip = self._slip_with_file()
        response = self.client.get(f"/media/{slip.slip_image_url}")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)



class SlipValidationTests(BaseSlipTestCase):
    """ตรวจไฟล์/สิทธิ์/สถานะออเดอร์ก่อนรับสลิป"""

    def test_rejects_non_image_file(self):
        bad = SimpleUploadedFile('slip.png', b'not-an-image', content_type='image/png')
        response = self._upload_slip(slip_file=bad)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'SLIP_INVALID_FILE')
        self.assertFalse(SlipTransaction.objects.filter(order=self.order).exists())

    def test_rejects_wrong_content_type(self):
        bad = SimpleUploadedFile('slip.txt', b'hello', content_type='text/plain')
        response = self._upload_slip(slip_file=bad)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'SLIP_INVALID_FILE')

    def test_rejects_when_order_not_pending_payment(self):
        paid_order = self._create_order(order_number='ORD-SLIP-PAID', order_status=OrderStatus.PAID)
        self.client.force_authenticate(user=self.customer)
        response = self.client.post(
            reverse('order-upload-slip', kwargs={'order_id': paid_order.id}),
            {'slip_image': make_slip_image()},
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data['error_code'], 'ORDER_ALREADY_PAID')

    def test_rejects_other_customer_order(self):
        other = User.objects.create(
            display_name='ลูกค้าคนอื่น', email='other@example.com', role=UserRole.CUSTOMER
        )
        CustomerProfile.objects.create(user=other, default_delivery_address='ที่อยู่อื่น')
        response = self._upload_slip(user=other)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error_code'], 'ORDER_NOT_FOUND')

    def test_attempt_limit_returns_429(self):
        with self.settings(SLIP_MAX_ATTEMPTS=1), \
                patch('apps.payments.services.create_and_send_notification'):
            first = self._upload_slip()
            self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
            second = self._upload_slip()

        self.assertEqual(second.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(second.data['error_code'], 'SLIP_ATTEMPTS_EXCEEDED')
        self.assertEqual(SlipTransaction.objects.filter(order=self.order).count(), 1)

    def test_only_one_pending_slip_per_order(self):
        self._make_pending_slip(trans_ref='MANUAL-FIRST')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._make_pending_slip(trans_ref='MANUAL-SECOND', attempt_no=2)


class SlipReviewTests(BaseSlipTestCase):
    """P0-01: แอดมินอนุมัติ/ปฏิเสธสลิป"""

    def setUp(self):
        super().setUp()
        self.slip = self._make_pending_slip()

    def _approve(self, user=None, payload=None):
        self.client.force_authenticate(user=user or self.admin)
        return self.client.post(
            reverse('admin-slip-approve', kwargs={'slip_id': self.slip.id}),
            payload if payload is not None else {'note': 'ยอดเงินตรงกับออเดอร์'},
            format='json',
        )

    def _reject(self, user=None, payload=None):
        self.client.force_authenticate(user=user or self.admin)
        return self.client.post(
            reverse('admin-slip-reject', kwargs={'slip_id': self.slip.id}),
            payload if payload is not None else {'reason': 'ยอดเงินไม่ตรง'},
            format='json',
        )

    def test_approve_transitions_order_to_paid(self):
        with patch('apps.payments.services.create_and_send_notification'):
            response = self._approve()

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['slip_status'], SlipStatus.APPROVED)
        self.assertEqual(response.data['data']['order_status'], OrderStatus.PAID)

        self.slip.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.slip.status, SlipStatus.APPROVED)
        self.assertTrue(self.slip.is_verified)
        self.assertEqual(self.slip.reviewer_id, self.admin.id)
        self.assertIsNotNone(self.slip.reviewed_at)
        self.assertEqual(self.order.status, OrderStatus.PAID)
        self.assertIsNotNone(self.order.paid_at)
        self.assertTrue(
            OrderStatusLog.objects.filter(
                order=self.order, to_status=OrderStatus.PAID, role='ADMIN'
            ).exists()
        )

    def test_reject_requires_reason(self):
        response = self._reject(payload={})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'REJECT_REASON_REQUIRED')
        self.slip.refresh_from_db()
        self.assertEqual(self.slip.status, SlipStatus.PENDING)

    def test_reject_keeps_order_pending(self):
        with patch('apps.payments.services.create_and_send_notification'):
            response = self._reject()

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['slip_status'], SlipStatus.REJECTED)
        self.assertEqual(response.data['data']['attempts_left'], 2)

        self.slip.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.slip.status, SlipStatus.REJECTED)
        self.assertEqual(self.slip.reject_reason, 'ยอดเงินไม่ตรง')
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)

    def test_cannot_review_slip_twice(self):
        with patch('apps.payments.services.create_and_send_notification'):
            self.assertEqual(self._approve().status_code, status.HTTP_200_OK)
            second = self._approve()

        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data['error_code'], 'SLIP_ALREADY_REVIEWED')

    def test_approve_unknown_slip_returns_404(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            reverse(
                'admin-slip-approve',
                kwargs={'slip_id': '00000000-0000-0000-0000-000000000000'},
            ),
            {},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['error_code'], 'SLIP_NOT_FOUND')

    def test_non_admin_cannot_review(self):
        self.assertEqual(self._approve(user=self.customer).status_code, status.HTTP_403_FORBIDDEN)
        self.slip.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.slip.status, SlipStatus.PENDING)
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)

    def test_merchant_cannot_review(self):
        self.assertEqual(self._reject(user=self.merchant_user).status_code, status.HTTP_403_FORBIDDEN)

    def test_slip_list_for_admin(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse('admin-slip-list'), {'status': 'PENDING'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['meta']['pending_total'], 1)
        self.assertEqual(len(response.data['data']), 1)

    def test_slip_list_rejects_bad_status_filter(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse('admin-slip-list'), {'status': 'WHATEVER'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'INVALID_STATUS')


def _provider_payload(amount='245.00', trans_ref='PROVIDER-REF-0001'):
    return {
        'is_success': True,
        'trans_ref': trans_ref,
        'amount': amount,
        # ต้องตรงกับบัญชี PromptPay ของแพลตฟอร์ม (ถ้ามีการตั้งค่า env ไว้)
        'receiving_account': os.environ.get('PLATFORM_PROMPTPAY_ACCOUNT') or '0000000000',
        'raw_payload': {'source': 'test'},
    }


class ApiModeSlipTests(BaseSlipTestCase):
    """โหมด API: ตรวจอัตโนมัติและเปลี่ยนสถานะผ่าน transition_order เท่านั้น"""

    def test_auto_approve_transitions_to_paid(self):
        with self.settings(PAYMENT_VERIFICATION_MODE='API'), \
                patch('apps.payments.services.call_slip_verify_api',
                      return_value=_provider_payload()) as mock_api, \
                patch('apps.payments.services.create_and_send_notification'):
            response = self._upload_slip()

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['slip_status'], SlipStatus.APPROVED)
        self.assertEqual(response.data['data']['order_status'], OrderStatus.PAID)
        self.assertEqual(mock_api.call_count, 1)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAID)
        slip = SlipTransaction.objects.get(order=self.order)
        self.assertEqual(slip.trans_ref, 'PROVIDER-REF-0001')
        self.assertTrue(slip.is_verified)
        self.assertEqual(slip.status, SlipStatus.APPROVED)
        self.assertTrue(
            OrderStatusLog.objects.filter(
                order=self.order, to_status=OrderStatus.PAID, role='SYSTEM'
            ).exists()
        )

    def test_amount_mismatch_is_rejected(self):
        with self.settings(PAYMENT_VERIFICATION_MODE='API'), \
                patch('apps.payments.services.call_slip_verify_api',
                      return_value=_provider_payload(amount='100.00')):
            response = self._upload_slip()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error_code'], 'SLIP_VERIFICATION_FAILED')

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)
        slip = SlipTransaction.objects.get(order=self.order)
        self.assertEqual(slip.status, SlipStatus.REJECTED)
        self.assertFalse(slip.is_verified)

    def test_hybrid_provider_failure_falls_back_to_pending(self):
        with self.settings(PAYMENT_VERIFICATION_MODE='HYBRID'), \
                patch('apps.payments.services.call_slip_verify_api',
                      side_effect=Exception('provider down')), \
                patch('apps.payments.services.create_and_send_notification'):
            response = self._upload_slip()

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['slip_status'], SlipStatus.PENDING)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)
        slip = SlipTransaction.objects.get(order=self.order)
        self.assertEqual(slip.status, SlipStatus.PENDING)
        self.assertEqual(slip.raw_payload.get('mode'), 'HYBRID')

