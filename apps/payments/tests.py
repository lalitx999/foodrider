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


# บัญชีรับเงินของร้านในการทดสอบ (กสิกร + พร้อมเพย์ e-Wallet) — ไม่ใช่ค่าจริงจาก .env
SHOP_ENV = {
    'SHOP_BANK_CODE': '004',
    'SHOP_BANK_ACCOUNT': '210-8-58346-3',
    'PLATFORM_PROMPTPAY_ACCOUNT': '004999214548470',
    'SHOP_ACCOUNT_NAMES': 'ทีเอ็มดับเบิ้ลพี,TMWP',
    'SLIP_VERIFY_API_KEY': '00000000-0000-4000-8000-000000000000',
}


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
        env = patch.dict(os.environ, SHOP_ENV)
        env.start()
        self.addCleanup(env.stop)
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


def _provider_payload(amount='245.00', trans_ref='PROVIDER-REF-0001', **overrides):
    payload = {
        'is_success': True,
        'trans_ref': trans_ref,
        'amount': amount,
        'receiver_bank_code': '004',
        'receiver_accounts': ['xxx-x-x8346-x'],
        'receiving_account': 'xxx-x-x8346-x',
        'receiver_names': ['ทีเอ็มดับเบิ้ลพี'],
        'is_duplicate': False,
        'raw_payload': {'source': 'test'},
    }
    payload.update(overrides)
    return payload


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



class ReceiverAndDuplicateTests(BaseSlipTestCase):
    """S-4: สลิปต้องโอนเข้าบัญชีร้านจริง · ไม่ตั้งค่าบัญชีร้าน = ไม่อนุมัติอัตโนมัติ · สลิปซ้ำถูกปฏิเสธ"""

    def _api_upload(self, payload):
        with self.settings(PAYMENT_VERIFICATION_MODE='API'), \
                patch('apps.payments.services.call_slip_verify_api', return_value=payload), \
                patch('apps.payments.services.create_and_send_notification'):
            return self._upload_slip()

    def _assert_rejected(self, response):
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PENDING_PAYMENT)

    def test_promptpay_ewallet_receiver_is_accepted(self):
        response = self._api_upload(_provider_payload(
            receiver_bank_code='004', receiver_accounts=['xxx-x-x8346-x', '004xxxxxxxx8470']
        ))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['order_status'], OrderStatus.PAID)

    def test_transfer_to_someone_else_is_rejected(self):
        self._assert_rejected(self._api_upload(_provider_payload(receiver_accounts=['xxx-x-x1234-x'])))
        self.assertIn('ไม่ได้โอนเข้าบัญชีของร้าน', SlipTransaction.objects.get().reject_reason)

    def test_same_last_digits_at_other_bank_is_rejected(self):
        self._assert_rejected(self._api_upload(_provider_payload(receiver_bank_code='014')))

    def test_slip_without_receiver_account_is_rejected(self):
        self._assert_rejected(self._api_upload(_provider_payload(receiver_accounts=[], receiving_account=None)))

    def test_no_shop_account_configured_never_auto_approves(self):
        with patch.dict(os.environ, {'SHOP_BANK_ACCOUNT': '', 'PLATFORM_PROMPTPAY_ACCOUNT': ''}):
            self._assert_rejected(self._api_upload(_provider_payload()))

    def test_receiver_name_must_match_shop(self):
        self._assert_rejected(self._api_upload(_provider_payload(receiver_names=['นาย สมชาย ใจดี'])))
        self.assertIn('ชื่อผู้รับ', SlipTransaction.objects.get().reject_reason)

    def test_slip_without_receiver_name_is_rejected(self):
        self._assert_rejected(self._api_upload(_provider_payload(receiver_names=[])))

    def test_no_shop_name_configured_never_auto_approves(self):
        with patch.dict(os.environ, {'SHOP_ACCOUNT_NAMES': ''}):
            self._assert_rejected(self._api_upload(_provider_payload()))

    def test_provider_duplicate_flag_is_rejected(self):
        self._assert_rejected(self._api_upload(_provider_payload(is_duplicate=True)))

    def test_hybrid_wrong_receiver_goes_to_admin(self):
        with self.settings(PAYMENT_VERIFICATION_MODE='HYBRID'), \
                patch('apps.payments.services.call_slip_verify_api',
                      return_value=_provider_payload(receiver_accounts=['xxx-x-x1234-x'])), \
                patch('apps.payments.services.create_and_send_notification'):
            response = self._upload_slip()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['slip_status'], SlipStatus.PENDING)


class MaskedAccountTests(TestCase):
    def test_matching_rules(self):
        from apps.payments.services import masked_account_matches

        self.assertTrue(masked_account_matches('xxx-x-x8346-x', '2108583463'))
        self.assertTrue(masked_account_matches('004xxxxxxxx8470', '004999214548470'))
        self.assertFalse(masked_account_matches('xxx-x-x8347-x', '2108583463'))
        self.assertFalse(masked_account_matches('xxx-x-xxx46-x', '2108583463'))  # เห็นน้อยกว่า 4 หลัก
        self.assertFalse(masked_account_matches('', '2108583463'))
        self.assertFalse(masked_account_matches('xxx-x-x8346-x', ''))


EASYSLIP_V2_SUCCESS = {
    'success': True,
    'message': 'Bank slip verified successfully',
    'data': {
        'isDuplicate': False,
        'matchedAccount': None,
        'amountInSlip': 245.0,
        'rawSlip': {
            'transRef': '68370160657749I376388B35',
            'date': '2024-01-15T14:30:00+07:00',
            'amount': {'amount': 245.0, 'local': {'amount': 245.0, 'currency': 'THB'}},
            'sender': {
                'bank': {'id': '014', 'name': 'ไทยพาณิชย์', 'short': 'SCB'},
                'account': {'name': {'th': 'นาย ผู้โอน ทดสอบ'}, 'bank': {'type': 'BANKAC', 'account': '123-4-xxxxx-5'}},
            },
            'receiver': {
                'bank': {'id': '004', 'name': 'กสิกรไทย', 'short': 'KBANK'},
                'account': {
                    'name': {'th': 'ทีเอ็มดับเบิ้ลพี'},
                    'bank': {'type': 'BANKAC', 'account': 'xxx-x-x8346-x'},
                    'proxy': {'type': 'EWALLETID', 'account': '004xxxxxxxx8470'},
                },
            },
        },
    },
}


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class ReceiverNameTests(TestCase):
    def test_matching_rules(self):
        from apps.payments.services import receiver_name_matches

        shop = ['ทีเอ็มดับเบิ้ลพี', 'tmwp']
        self.assertTrue(receiver_name_matches(['ทีเอ็มดับเบิ้ลพี'], shop))
        self.assertTrue(receiver_name_matches(['ร้าน ทีเอ็ม ดับเบิ้ลพี'], shop))  # คำนำหน้า + ช่องว่าง
        self.assertTrue(receiver_name_matches(['T.M.W.P.'], shop))
        self.assertTrue(receiver_name_matches(['ทีเอ็มดับเบิ้'], shop))  # ธนาคารตัดชื่อยาว
        self.assertFalse(receiver_name_matches(['นาย สมชาย ใจดี'], shop))
        self.assertFalse(receiver_name_matches(['ที'], shop))  # สั้นเกินจะเชื่อได้
        self.assertFalse(receiver_name_matches([], shop))


class EasySlipClientTests(TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {**SHOP_ENV, 'SLIP_VERIFY_API_URL': ''})
        env.start()
        self.addCleanup(env.stop)

    def _call(self, response):
        from apps.payments.services import call_slip_verify_api

        with patch('apps.payments.services.requests.post', return_value=response) as post:
            result = call_slip_verify_api(make_slip_image(), expected_amount=Decimal('245.00'), remark='ORD-1')
        return result, post

    def test_success_is_normalized_and_request_follows_v2_contract(self):
        result, post = self._call(FakeResponse(200, EASYSLIP_V2_SUCCESS))
        self.assertEqual(result['trans_ref'], '68370160657749I376388B35')
        self.assertEqual(result['amount'], '245.0')
        self.assertEqual(result['receiver_bank_code'], '004')
        self.assertEqual(result['receiver_accounts'], ['xxx-x-x8346-x', '004xxxxxxxx8470'])
        self.assertEqual(result['sending_bank'], 'SCB')
        self.assertEqual(result['receiver_names'], ['ทีเอ็มดับเบิ้ลพี'])
        self.assertFalse(result['is_duplicate'])

        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://api.easyslip.com/v2/verify/bank')
        self.assertEqual(kwargs['headers']['Authorization'], f"Bearer {SHOP_ENV['SLIP_VERIFY_API_KEY']}")
        self.assertIn('image', kwargs['files'])
        self.assertEqual(kwargs['data']['checkDuplicate'], 'true')
        self.assertEqual(kwargs['data']['matchAmount'], '245.00')
        self.assertEqual(kwargs['data']['remark'], 'ORD-1')

    def test_normalized_slip_passes_order_check(self):
        from apps.payments.services import _check_slip_against_order

        result, _ = self._call(FakeResponse(200, EASYSLIP_V2_SUCCESS))
        order = type('O', (), {'total_amount': Decimal('245.00')})()
        self.assertEqual(_check_slip_against_order(result, order), Decimal('245.00'))

    def test_slip_problems_raise_customer_facing_error(self):
        from apps.payments.services import SlipVerificationError

        for code in ('SLIP_NOT_FOUND', 'slip_pending', 'INVALID_IMAGE_FORMAT'):
            with self.assertRaises(SlipVerificationError):
                self._call(FakeResponse(404, {'success': False, 'error': {'code': code, 'message': 'x'}}))

    def test_provider_problems_raise_provider_error(self):
        from apps.payments.services import SlipProviderError

        for status_code, code in ((403, 'QUOTA_EXCEEDED'), (401, 'INVALID_API_KEY'), (403, 'IP_NOT_ALLOWED'), (500, 'API_SERVER_ERROR')):
            with self.assertRaises(SlipProviderError):
                self._call(FakeResponse(status_code, {'success': False, 'error': {'code': code, 'message': 'x'}}))

    def test_missing_key_is_provider_error(self):
        from apps.payments.services import SlipProviderError, call_slip_verify_api

        with patch.dict(os.environ, {'SLIP_VERIFY_API_KEY': ''}), patch('apps.payments.services.requests.post') as post:
            with self.assertRaises(SlipProviderError):
                call_slip_verify_api(make_slip_image())
        post.assert_not_called()


class PromptPayQrTests(TestCase):
    def test_ewallet_id_builds_tag_03(self):
        from apps.payments import promptpay

        with patch.dict(os.environ, {'PLATFORM_PROMPTPAY_ACCOUNT': '004999214548470'}), \
                patch.object(promptpay.qrcode, 'make', wraps=promptpay.qrcode.make) as make:
            _, account = promptpay.create_promptpay_qr('245.00')
        payload = make.call_args[0][0]
        self.assertEqual(account, '004999214548470')
        self.assertIn('29390016A000000677010111' + '0315004999214548470', payload)
        self.assertIn('5406245.00', payload)
        self.assertEqual(promptpay._crc16(payload[:-4]), payload[-4:])
