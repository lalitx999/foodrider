import logging
import os
import uuid
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.notifications.fcm import create_and_send_notification
from apps.orders.models import Order, OrderStatus
from apps.orders.services import transition_order
from apps.payments.models import SlipStatus, SlipTransaction
from apps.users.models import User, UserRole

logger = logging.getLogger(__name__)


class SlipVerificationError(Exception):
    """Custom Exception สำหรับความผิดพลาดในการตรวจสอบสลิป"""


class SlipReviewError(Exception):
    """เกิดเมื่อการตรวจ/อนุมัติสลิปไม่ผ่านเงื่อนไข (มี error_code ติดไปกับ response)"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def call_slip_verify_api(image_file) -> dict:
    """
    ยิงไปตรวจสอบสลิปโอนเงินกับ Slip Verification API ภายนอก (SlipOK / OpenSlip)
    """
    api_url = os.environ.get('SLIP_VERIFY_API_URL')
    api_key = os.environ.get('SLIP_VERIFY_API_KEY')

    if not api_url or not api_key or api_key == 'your_slip_verify_api_key':
        raise SlipVerificationError('ยังไม่ได้ตั้งค่าผู้ให้บริการตรวจสอบสลิป')

    try:
        headers = {'x-authorization': api_key}
        files = {'files': image_file}
        response = requests.post(api_url, headers=headers, files=files, timeout=15)
        
        if response.status_code != 200:
            raise SlipVerificationError("ไม่สามารถเชื่อมต่อระบบตรวจสอบสลิปได้")

        res_data = response.json()
        if not res_data.get('success', False):
            raise SlipVerificationError(res_data.get('message', 'สลิปไม่ถูกต้อง หรือไม่สามารถอ่าน QR Code ได้'))

        data = res_data.get('data', {})
        return {
            'is_success': True,
            'trans_ref': data.get('transRef'),
            'sending_bank': data.get('sendingBank'),
            'receiving_bank': data.get('receivingBank'),
            'sender_name': data.get('sender', {}).get('displayName'),
            'amount': str(data.get('amount', 0)),
            'receiving_account': data.get('receiver', {}).get('proxy', {}).get('value'),
            'raw_payload': res_data
        }
    except requests.RequestException as e:
        raise SlipVerificationError(f"เกิดข้อผิดพลาดในการเชื่อมต่อระบบตรวจสลิป: {str(e)}")


def _check_slip_against_order(slip_data: dict, order: Order) -> Decimal:
    """ตรวจสลิปซ้ำ / บัญชีผู้รับ / ยอดเงิน (Decimal equality) — คืนยอดเงินที่อ่านได้"""
    trans_ref = slip_data.get('trans_ref')
    if not trans_ref:
        raise SlipVerificationError('ไม่พบรหัสอ้างอิงธุรกรรมในสลิป')

    if SlipTransaction.objects.filter(trans_ref=trans_ref).exists():
        raise SlipVerificationError('สลิปนี้ถูกนำมาใช้งานในระบบไปแล้ว (Double Spending Detected)')

    system_account = os.environ.get('PLATFORM_PROMPTPAY_ACCOUNT')
    receiving_account = slip_data.get('receiving_account')
    if system_account and receiving_account and receiving_account != system_account:
        raise SlipVerificationError('ยอดเงินในสลิปไม่ได้โอนเข้าบัญชี PromptPay ของแพลตฟอร์ม')

    try:
        amount = Decimal(str(slip_data.get('amount')))
    except (InvalidOperation, TypeError, ValueError):
        raise SlipVerificationError('ไม่สามารถอ่านยอดเงินจากสลิปได้')

    if amount != order.total_amount:
        raise SlipVerificationError(
            f'ยอดเงินในสลิป ({amount} บาท) ไม่ตรงกับยอดที่ต้องชำระ ({order.total_amount} บาท)'
        )
    return amount


def _next_attempt_no(order: Order) -> int:
    max_attempts = int(getattr(settings, 'SLIP_MAX_ATTEMPTS', 3))
    attempt_no = order.slip_transactions.count() + 1
    if attempt_no > max_attempts:
        raise SlipReviewError(
            'SLIP_ATTEMPTS_EXCEEDED',
            f'อัปโหลดสลิปครบ {max_attempts} ครั้งแล้ว กรุณาติดต่อแอดมิน',
        )
    return attempt_no


def _notify_admins_new_slip(order: Order, slip: SlipTransaction) -> None:
    body = f'ออเดอร์ {order.order_number} มียอด {order.total_amount} บาท รอตรวจสอบสลิป'
    for admin in User.objects.filter(role=UserRole.ADMIN, is_active=True):
        try:
            create_and_send_notification(
                user=admin,
                title='มีสลิปใหม่รอตรวจสอบ',
                body=body,
                data={'type': 'SLIP_PENDING', 'order_id': str(order.id), 'slip_id': str(slip.id)},
            )
        except Exception:  # การแจ้งเตือนต้องไม่ทำให้การอัปโหลดสลิปล้มเหลว
            logger.exception('Cannot notify admin %s about slip %s', admin.id, slip.id)


def verify_and_process_order_slip(order: Order, slip_image, slip_image_url: str) -> SlipTransaction:
    """
    อัปโหลดสลิป (P0-01):
    - MANUAL (default): บันทึกสลิปเป็น PENDING และ **ไม่แตะสถานะออเดอร์** + แจ้งแอดมิน
    - API: ตรวจกับผู้ให้บริการทันที ผ่าน → APPROVED + transition_order(PAID) / ไม่ผ่าน → REJECTED
    - HYBRID: ผ่าน → auto approve, ไม่ผ่าน/ตรวจไม่ได้ → ตกไป PENDING ให้แอดมินตรวจ

    ป้องกันสลิปซ้ำ/ยอดไม่ตรง/สลิปค้างซ้อนกัน (1 PENDING ต่อออเดอร์) และจำกัดจำนวนครั้ง
    """
    mode = getattr(settings, 'PAYMENT_VERIFICATION_MODE', 'MANUAL')

    if order.status != OrderStatus.PENDING_PAYMENT:
        raise SlipReviewError('ORDER_ALREADY_PAID', 'ออเดอร์นี้ไม่อยู่ในสถานะรอชำระเงิน')

    # จำกัดจำนวนครั้งก่อนยิงผู้ให้บริการ (กันการยิงซ้ำในโหมด API ที่สลิปถูกปฏิเสธ)
    max_attempts = int(getattr(settings, 'SLIP_MAX_ATTEMPTS', 3))
    if order.slip_transactions.count() + 1 > max_attempts:
        raise SlipReviewError(
            'SLIP_ATTEMPTS_EXCEEDED',
            f'อัปโหลดสลิปครบ {max_attempts} ครั้งแล้ว กรุณาติดต่อแอดมิน',
        )

    slip_data = None
    provider_failure = None

    if mode in {'API', 'HYBRID'}:
        try:
            slip_data = call_slip_verify_api(slip_image)
            _check_slip_against_order(slip_data, order)
        except SlipVerificationError as exc:
            provider_failure = str(exc)
            slip_data = None
            if mode == 'API':
                _record_rejected_slip(order, slip_image_url, provider_failure)
                raise
        except Exception:
            # ผู้ให้บริการล่ม/timeout — HYBRID ต้องตกไปให้แอดมินตรวจ ไม่ทำให้ลูกค้าอัปโหลดไม่ได้
            logger.exception('Slip verification provider error (order %s)', order.id)
            provider_failure = 'ไม่สามารถตรวจสอบสลิปอัตโนมัติได้'
            slip_data = None
            if mode == 'API':
                _record_rejected_slip(order, slip_image_url, provider_failure)
                raise SlipVerificationError(provider_failure)

    with transaction.atomic():
        locked_order = Order.objects.select_for_update().get(pk=order.pk)
        if locked_order.status != OrderStatus.PENDING_PAYMENT:
            raise SlipReviewError('ORDER_ALREADY_PAID', 'ออเดอร์นี้ได้รับการยืนยันการชำระเงินแล้ว')

        attempt_no = _next_attempt_no(locked_order)
        SlipTransaction.objects.filter(order=locked_order, status=SlipStatus.PENDING).update(
            status=SlipStatus.SUPERSEDED
        )

        if slip_data is not None:
            slip = SlipTransaction.objects.create(
                order=locked_order,
                trans_ref=slip_data['trans_ref'],
                sending_bank=slip_data.get('sending_bank'),
                receiving_bank=slip_data.get('receiving_bank'),
                sender_name=slip_data.get('sender_name'),
                amount=Decimal(str(slip_data['amount'])),
                slip_image_url=slip_image_url,
                is_verified=True,
                status=SlipStatus.APPROVED,
                attempt_no=attempt_no,
                reviewed_at=timezone.now(),
                raw_payload=slip_data.get('raw_payload', {}),
            )
            transition_order(
                locked_order,
                OrderStatus.PAID,
                role='SYSTEM',
                note=f'ตรวจสลิปอัตโนมัติผ่าน (โหมด {mode})',
            )
            transaction.on_commit(lambda: _notify_slip_approved(locked_order))
            return slip

        slip = SlipTransaction.objects.create(
            order=locked_order,
            trans_ref=f'MANUAL-{uuid.uuid4().hex[:10].upper()}',
            sending_bank=slip_data.get('sending_bank') if slip_data else None,
            receiving_bank=slip_data.get('receiving_bank') if slip_data else None,
            sender_name=(
                slip_data.get('sender_name')
                if slip_data
                else (locked_order.customer.display_name if locked_order.customer else None)
            ),
            amount=locked_order.total_amount,
            slip_image_url=slip_image_url,
            is_verified=False,
            status=SlipStatus.PENDING,
            attempt_no=attempt_no,
            raw_payload={'mode': mode, 'provider_failure': provider_failure},
        )
        transaction.on_commit(lambda: _notify_admins_new_slip(locked_order, slip))
        return slip

def _record_rejected_slip(order: Order, slip_image_url: str, reason: str) -> SlipTransaction:
    """โหมด API: บันทึกสลิปที่ตรวจไม่ผ่านเป็น REJECTED (ไม่แตะสถานะออเดอร์)"""
    return SlipTransaction.objects.create(
        order=order,
        trans_ref=f'REJECTED-{uuid.uuid4().hex[:10].upper()}',
        amount=order.total_amount,
        slip_image_url=slip_image_url,
        is_verified=False,
        status=SlipStatus.REJECTED,
        attempt_no=order.slip_transactions.count() + 1,
        reviewed_at=timezone.now(),
        reject_reason=reason,
        raw_payload={'mode': 'API'},
    )


def _safe_notify(user, *, title: str, body: str, data: dict) -> None:
    if not user:
        return
    try:
        create_and_send_notification(user=user, title=title, body=body, data=data)
    except Exception:  # การแจ้งเตือนต้องไม่ทำให้ flow การเงินล้มเหลว
        logger.exception('Cannot send notification to user %s', user.id)


def _notify_slip_approved(order: Order) -> None:
    title = 'ยืนยันการชำระเงินแล้ว'
    body = f'ออเดอร์ {order.order_number} ชำระเงินเรียบร้อย ร้านกำลังเตรียมอาหาร'
    data = {'type': 'ORDER_PAID', 'order_id': str(order.id), 'status': OrderStatus.PAID}
    _safe_notify(order.customer, title=title, body=body, data=data)
    merchant_user = order.merchant.user if order.merchant_id else None
    _safe_notify(
        merchant_user,
        title='มีออเดอร์ที่ชำระเงินแล้ว',
        body=f'ออเดอร์ {order.order_number} พร้อมให้เตรียมอาหาร',
        data={'type': 'ORDER_PAID', 'order_id': str(order.id), 'status': OrderStatus.PAID},
    )


def _notify_slip_rejected(order: Order, reason: str, remaining_attempts: int) -> None:
    body = f'สลิปออเดอร์ {order.order_number} ไม่ผ่านการตรวจสอบ: {reason}'
    if remaining_attempts > 0:
        body += f' (อัปโหลดใหม่ได้อีก {remaining_attempts} ครั้ง)'
    else:
        body += ' (ครบจำนวนครั้งที่อัปโหลดได้แล้ว กรุณาติดต่อแอดมิน)'
    _safe_notify(
        order.customer,
        title='สลิปไม่ผ่านการตรวจสอบ',
        body=body,
        data={'type': 'SLIP_REJECTED', 'order_id': str(order.id), 'reason': reason},
    )


@transaction.atomic
def approve_slip(slip_id, reviewer, *, note: str = '') -> SlipTransaction:
    """แอดมินอนุมัติสลิป → slip APPROVED + order transition_order(PAID) (BR-5/BR-6)"""
    try:
        slip = SlipTransaction.objects.select_for_update().get(pk=slip_id)
    except SlipTransaction.DoesNotExist:
        raise SlipReviewError('SLIP_NOT_FOUND', 'ไม่พบสลิปที่ระบุ')

    if slip.status != SlipStatus.PENDING:
        raise SlipReviewError('SLIP_ALREADY_REVIEWED', f'สลิปนี้ถูกตรวจสอบแล้ว (สถานะ {slip.status})')

    order = Order.objects.select_for_update().get(pk=slip.order_id)
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise SlipReviewError('ORDER_NOT_PAID', f'ออเดอร์นี้ไม่สามารถยืนยันการชำระเงินได้ (สถานะ {order.status})')

    slip.status = SlipStatus.APPROVED
    slip.is_verified = True
    slip.reviewer = reviewer if getattr(reviewer, 'is_authenticated', False) else None
    slip.reviewed_at = timezone.now()
    slip.reject_reason = None
    slip.save(update_fields=['status', 'is_verified', 'reviewer', 'reviewed_at', 'reject_reason'])

    transition_order(
        order,
        OrderStatus.PAID,
        actor=reviewer,
        role='ADMIN',
        note=note or 'แอดมินอนุมัติสลิป',
    )
    transaction.on_commit(lambda: _notify_slip_approved(order))
    return slip


@transaction.atomic
def reject_slip(slip_id, reviewer, *, reason: str) -> SlipTransaction:
    """แอดมินปฏิเสธสลิป (ต้องระบุเหตุผล) — ไม่แตะสถานะออเดอร์"""
    reason = (reason or '').strip()
    if not reason:
        raise SlipReviewError('REJECT_REASON_REQUIRED', 'กรุณาระบุเหตุผลที่ปฏิเสธสลิป')

    try:
        slip = SlipTransaction.objects.select_for_update().get(pk=slip_id)
    except SlipTransaction.DoesNotExist:
        raise SlipReviewError('SLIP_NOT_FOUND', 'ไม่พบสลิปที่ระบุ')

    if slip.status != SlipStatus.PENDING:
        raise SlipReviewError('SLIP_ALREADY_REVIEWED', f'สลิปนี้ถูกตรวจสอบแล้ว (สถานะ {slip.status})')

    slip.status = SlipStatus.REJECTED
    slip.is_verified = False
    slip.reviewer = reviewer if getattr(reviewer, 'is_authenticated', False) else None
    slip.reviewed_at = timezone.now()
    slip.reject_reason = reason
    slip.save(update_fields=['status', 'is_verified', 'reviewer', 'reviewed_at', 'reject_reason'])

    max_attempts = int(getattr(settings, 'SLIP_MAX_ATTEMPTS', 3))
    remaining = max(0, max_attempts - slip.attempt_no)
    order = slip.order
    transaction.on_commit(lambda: _notify_slip_rejected(order, reason, remaining))
    return slip

