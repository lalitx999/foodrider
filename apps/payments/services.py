import logging
import os
import unicodedata
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


EASYSLIP_V2_URL = 'https://api.easyslip.com/v2/verify/bank'
PLACEHOLDER_KEYS = {'', 'your_slip_verify_api_key', 'replace-with-slip-provider-key'}

# error code จาก EasySlip ที่เป็นปัญหาของ "สลิป" (บอกลูกค้าได้) — โค้ดอื่น (คีย์/โควต้า/IP/ระบบล่ม) เป็นปัญหาฝั่งเรา
SLIP_PROBLEM_MESSAGES = {
    'SLIP_NOT_FOUND': 'อ่าน QR บนสลิปไม่ได้ หรือไม่พบรายการโอนนี้ — ถ่ายสลิปให้เห็น QR ชัดๆ แล้วลองใหม่',
    'QRCODE_NOT_FOUND': 'ไม่พบ QR บนสลิป — ใช้รูปสลิปจากแอปธนาคารโดยตรง',
    'SLIP_PENDING': 'ธนาคารยังไม่ยืนยันรายการนี้ (สลิปกรุงเทพต้องรอประมาณ 5 นาที) — ลองส่งใหม่อีกครั้ง',
    'SLIP_EXPIRED': 'สลิปนี้เก่าเกินกว่าจะตรวจสอบได้',
    'INVALID_IMAGE_FORMAT': 'ไฟล์นี้ไม่ใช่รูปภาพที่ระบบอ่านได้ (ใช้ JPG / PNG)',
    'INVALID_IMAGE': 'ไฟล์นี้ไม่ใช่รูปภาพที่ระบบอ่านได้ (ใช้ JPG / PNG)',
    'IMAGE_SIZE_TOO_LARGE': 'รูปสลิปใหญ่เกิน 4MB',
    'DUPLICATE_SLIP': 'สลิปนี้ถูกนำมาใช้งานในระบบไปแล้ว (Double Spending Detected)',
}


class SlipProviderError(Exception):
    """ผู้ให้บริการตรวจสลิปใช้งานไม่ได้ (คีย์ผิด/โควต้าหมด/IP ไม่อนุญาต/ระบบล่ม) — ไม่ใช่ความผิดของสลิป"""


def call_slip_verify_api(image_file, *, expected_amount=None, remark: str = '') -> dict:
    """
    ตรวจสลิปกับ EasySlip API V2 — POST /v2/verify/bank (multipart field `image`)
    https://document.easyslip.com/th/v2/verify/bank/image

    คืน dict รูปแบบกลางของระบบ (ไม่ผูกกับผู้ให้บริการ) ให้ `_check_slip_against_order` ตรวจต่อ
    - สลิปมีปัญหา → SlipVerificationError (ข้อความบอกลูกค้าได้)
    - ผู้ให้บริการใช้ไม่ได้ → SlipProviderError (โหมด HYBRID จะส่งให้แอดมินตรวจแทน)
    """
    api_url = os.environ.get('SLIP_VERIFY_API_URL') or EASYSLIP_V2_URL
    api_key = (os.environ.get('SLIP_VERIFY_API_KEY') or '').strip()
    if api_key in PLACEHOLDER_KEYS:
        raise SlipProviderError('ยังไม่ได้ตั้งค่า SLIP_VERIFY_API_KEY')

    form = {'checkDuplicate': 'true', 'matchAccount': 'true'}
    if expected_amount is not None:
        form['matchAmount'] = str(expected_amount)
    if remark:
        form['remark'] = remark[:255]

    filename = getattr(image_file, 'name', None) or 'slip.jpg'
    content_type = getattr(image_file, 'content_type', None) or 'image/jpeg'
    try:
        response = requests.post(
            api_url,
            headers={'Authorization': f'Bearer {api_key}'},
            files={'image': (os.path.basename(filename), image_file, content_type)},
            data=form,
            timeout=20,
        )
    except requests.RequestException as error:
        raise SlipProviderError(f'เชื่อมต่อ EasySlip ไม่ได้: {error}') from error

    try:
        body = response.json()
    except ValueError:
        raise SlipProviderError(f'EasySlip ตอบกลับไม่ใช่ JSON (HTTP {response.status_code})')

    if response.status_code != 200 or not body.get('success'):
        error = body.get('error') if isinstance(body.get('error'), dict) else {}
        code = str(error.get('code') or body.get('message') or '').upper()
        if code in SLIP_PROBLEM_MESSAGES:
            raise SlipVerificationError(SLIP_PROBLEM_MESSAGES[code])
        raise SlipProviderError(f'EasySlip error HTTP {response.status_code} {code or "-"}')

    return normalize_easyslip_v2(body)


def normalize_easyslip_v2(body: dict) -> dict:
    """แปลง response V2 (`data.rawSlip`) เป็นรูปแบบกลาง"""
    data = body.get('data') or {}
    raw = data.get('rawSlip') or {}
    sender = raw.get('sender') or {}
    receiver = raw.get('receiver') or {}
    receiver_account = receiver.get('account') or {}
    receiver_bank = receiver.get('bank') or {}
    sender_name = (sender.get('account') or {}).get('name') or {}
    receiver_name = receiver_account.get('name') or {}

    accounts = []
    for key in ('bank', 'proxy'):
        value = (receiver_account.get(key) or {}).get('account')
        if value:
            accounts.append(str(value))

    amount = (raw.get('amount') or {}).get('amount')
    if amount is None:
        amount = data.get('amountInSlip')

    return {
        'is_success': True,
        'trans_ref': raw.get('transRef'),
        'sending_bank': (sender.get('bank') or {}).get('short'),
        'receiving_bank': receiver_bank.get('short'),
        'receiver_bank_code': receiver_bank.get('id'),
        'sender_name': sender_name.get('th') or sender_name.get('en'),
        'amount': str(amount) if amount is not None else None,
        'receiver_accounts': accounts,
        'receiver_names': [name for name in (receiver_name.get('th'), receiver_name.get('en')) if name],
        'receiving_account': accounts[0] if accounts else None,
        'account_matched': data.get('matchedAccount') is not None,
        'is_duplicate': bool(data.get('isDuplicate')),
        'raw_payload': body,
    }


def _digits(value) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def masked_account_matches(masked: str, actual: str) -> bool:
    """
    เทียบเลขบัญชีแบบปิดบังในสลิป (เช่น `xxx-x-x8346-x`) กับเลขจริง (`2108583463`)
    เทียบชิดขวาทีละหลัก: ทุกหลักที่เห็นต้องตรง และต้องเห็นอย่างน้อย 4 หลัก
    """
    pattern = ''.join(ch.lower() for ch in str(masked or '') if ch.isdigit() or ch.lower() == 'x')
    target = _digits(actual)
    if not pattern or not target:
        return False
    visible = 0
    for slip_char, real_char in zip(reversed(pattern), reversed(target)):
        if slip_char == 'x':
            continue
        if slip_char != real_char:
            return False
        visible += 1
    return visible >= 4


def shop_receiving_accounts() -> list[tuple[str | None, str]]:
    """บัญชีรับเงินของร้าน [(รหัสธนาคาร | None, เลข)] — บัญชีธนาคาร + พร้อมเพย์ที่ใช้สร้าง QR"""
    accounts = []
    bank_account = _digits(os.environ.get('SHOP_BANK_ACCOUNT'))
    if bank_account:
        accounts.append(((os.environ.get('SHOP_BANK_CODE') or '').strip() or None, bank_account))
    promptpay = _digits(os.environ.get('PLATFORM_PROMPTPAY_ACCOUNT'))
    if promptpay:
        accounts.append((None, promptpay))
    return accounts


def _receiver_is_shop(slip_data: dict) -> bool:
    shop_accounts = shop_receiving_accounts()
    if not shop_accounts:
        # ไม่ตั้งค่าบัญชีร้าน = ห้ามอนุมัติอัตโนมัติ (เดิมข้ามการตรวจไปเลย ทำให้สลิปโอนเข้าบัญชีใครก็ผ่าน)
        raise SlipVerificationError('ระบบยังไม่ได้ตั้งค่าบัญชีรับเงินของร้าน — ส่งให้แอดมินตรวจ')
    receiver_bank = (slip_data.get('receiver_bank_code') or '').strip()
    slip_accounts = slip_data.get('receiver_accounts') or (
        [slip_data['receiving_account']] if slip_data.get('receiving_account') else []
    )
    for masked in slip_accounts:
        for bank_code, number in shop_accounts:
            if bank_code and receiver_bank and bank_code != receiver_bank:
                continue
            if masked_account_matches(masked, number):
                return True
    return False


NAME_PREFIXES = (
    'นางสาว', 'น.ส.', 'นาย', 'นาง', 'บริษัท', 'บจก.', 'หจก.', 'ร้าน',
    'mr.', 'mrs.', 'ms.', 'miss', 'mr', 'mrs', 'ms', 'co.,ltd.', 'company limited',
)
MIN_NAME_CHARS = 4


def _normalize_name(value) -> str:
    text = str(value or '').strip().lower()
    for prefix in NAME_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # เก็บสระ/วรรณยุกต์ไทย (Unicode หมวด M) ไว้ด้วย — isalnum() ตัดทิ้ง ทำให้ชื่อต่างกันดูเหมือนกัน
    return ''.join(ch for ch in text if ch.isalnum() or unicodedata.category(ch).startswith('M'))


def shop_account_names() -> list[str]:
    """ชื่อบัญชีรับเงินของร้าน (คั่นด้วย , ได้หลายชื่อ เช่นชื่อไทย + อังกฤษ)"""
    raw = os.environ.get('SHOP_ACCOUNT_NAMES') or ''
    return [name for name in (_normalize_name(item) for item in raw.split(',')) if len(name) >= MIN_NAME_CHARS]


def receiver_name_matches(slip_names, shop_names) -> bool:
    """
    ชื่อผู้รับในสลิปต้องตรงกับชื่อบัญชีร้าน — ไม่สนคำนำหน้า/ช่องว่าง/จุด/ตัวพิมพ์
    บางธนาคารตัดชื่อยาวให้สั้นลง จึงยอมให้ชื่อหนึ่งเป็นส่วนต้นของอีกชื่อ (อย่างน้อย 4 ตัวอักษร)
    """
    for raw in slip_names or []:
        slip = _normalize_name(raw)
        if len(slip) < MIN_NAME_CHARS:
            continue
        for shop in (_normalize_name(name) for name in shop_names):
            if len(shop) < MIN_NAME_CHARS:
                continue
            if slip == shop or shop.startswith(slip) or slip.startswith(shop):
                return True
    return False


def _check_slip_against_order(slip_data: dict, order: Order) -> Decimal:
    """ตรวจสลิปซ้ำ / บัญชีผู้รับ / ชื่อผู้รับ / ยอดเงิน (Decimal equality) — ต้องตรงทั้งหมด คืนยอดเงินที่อ่านได้"""
    trans_ref = slip_data.get('trans_ref')
    if not trans_ref:
        raise SlipVerificationError('ไม่พบรหัสอ้างอิงธุรกรรมในสลิป')

    if SlipTransaction.objects.filter(trans_ref=trans_ref).exists() or slip_data.get('is_duplicate'):
        # is_duplicate: EasySlip เคยตรวจสลิปนี้แล้ว (เช่นเคยผ่านแอดมินตรวจมือที่ไม่ได้เก็บ transRef จริง)
        raise SlipVerificationError('สลิปนี้ถูกนำมาใช้งานในระบบไปแล้ว (Double Spending Detected)')

    if not _receiver_is_shop(slip_data):
        raise SlipVerificationError('สลิปนี้ไม่ได้โอนเข้าบัญชีของร้าน')

    shop_names = shop_account_names()
    if not shop_names:
        raise SlipVerificationError('ระบบยังไม่ได้ตั้งค่าชื่อบัญชีรับเงินของร้าน — ส่งให้แอดมินตรวจ')
    if not receiver_name_matches(slip_data.get('receiver_names'), shop_names):
        raise SlipVerificationError('ชื่อผู้รับในสลิปไม่ตรงกับชื่อบัญชีของร้าน')

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
            slip_data = call_slip_verify_api(
                slip_image, expected_amount=order.total_amount, remark=order.order_number
            )
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

