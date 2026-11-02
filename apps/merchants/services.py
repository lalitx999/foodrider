import logging
from decimal import Decimal
from uuid import uuid4

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename

from apps.merchants.models import BankChangeStatus, Category, Merchant, MerchantBankChangeRequest, MenuItem, MenuOption
from apps.users.bank_encryption import decrypt_bank_value, encrypt_bank_value

logger = logging.getLogger(__name__)

DEFAULT_RADIUS_KM = 10.0


def get_nearby_open_merchants(lat: float, lng: float, radius_km: float = DEFAULT_RADIUS_KM):
    """
    คืนร้านที่ "เปิดอยู่" และอยู่ในรัศมี `radius_km` เรียงจากใกล้สุด (P0-12)

    - GET ต้องไม่เขียน DB (ห้าม sync/backfill ในนี้) — ถ้าข้อมูลพิกัดไม่ครบ ให้ข้ามร้านนั้น
    - ไม่มี fallback "คืนทั้งประเทศ": นอกรัศมี = list ว่าง
    """
    try:
        user_location = Point(lng, lat, srid=4326)
        queryset = (
            Merchant.objects.filter(is_open=True)
            .exclude(location__isnull=True)
            .annotate(distance=Distance('location', user_location))
            .filter(distance__lte=D(km=radius_km))
            .order_by('distance')
        )

        result = []
        for merchant in queryset:
            merchant.distance_km = round(merchant.distance.m / 1000.0, 2) if merchant.distance else 0.0
            result.append(merchant)
        return result
    except Exception:
        # ห้ามให้ค้นหาร้าล้มทั้งหน้าเพราะข้อมูลพิกัดของร้านใดร้านหนึ่งเสีย
        logger.exception('get_nearby_open_merchants failed (lat=%s, lng=%s, radius=%s)', lat, lng, radius_km)
        return []


def get_merchant_full_menu(merchant_id: str):
    """
    ดึงโครงสร้าง หมวดหมู่ -> รายการอาหาร -> ตัวเลือกเสริม สำหรับฝั่งลูกค้า
    """
    categories = Category.objects.filter(merchant_id=merchant_id).prefetch_related(
        'items', 'items__options'
    ).order_by('sort_order', 'name')
    
    return categories


# ---------------------------------------------------------------------------
# ข้อมูลร้าน + คำขอเปลี่ยนบัญชีธนาคาร (module_32 เฟส A)
# ---------------------------------------------------------------------------
STOREFRONT_UPLOAD_DIR = 'merchant-storefronts'


class BankChangeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def mask_account_number(value: str, visible: int = 4) -> str:
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if not digits:
        return ''
    return f"{'*' * max(0, len(digits) - visible)}{digits[-visible:]}"


@transaction.atomic
def update_merchant_profile(merchant: Merchant, data: dict, image=None) -> Merchant:
    """
    แก้ข้อมูลหน้าร้าน (มีผลทันที) — ไม่แตะบัญชีธนาคาร
    data มาจาก MerchantProfileUpdateSerializer (validate แล้ว)
    """
    merchant = Merchant.objects.select_for_update().get(pk=merchant.pk)
    changed = []
    for field in ('name', 'description', 'phone_number', 'address'):
        if field in data:
            setattr(merchant, field, data[field])
            changed.append(field)

    if 'latitude' in data and 'longitude' in data:
        merchant.latitude = Decimal(str(data['latitude']))
        merchant.longitude = Decimal(str(data['longitude']))
        merchant.location = Point(float(data['longitude']), float(data['latitude']), srid=4326)
        changed += ['latitude', 'longitude', 'location']

    if image is not None:
        name = f"{STOREFRONT_UPLOAD_DIR}/{merchant.id}/{uuid4().hex}_{get_valid_filename(image.name)}"
        saved = default_storage.save(name, image)
        merchant.image_url = default_storage.url(saved)
        changed.append('image_url')

    if changed:
        merchant.save(update_fields=[*changed, 'updated_at'])
        logger.info('Merchant %s updated profile fields: %s', merchant.id, ', '.join(changed))
    return merchant


def _notify_admins_bank_change(merchant: Merchant, change: MerchantBankChangeRequest) -> None:
    from apps.notifications.fcm import create_and_send_notification
    from apps.users.models import User, UserRole

    for admin in User.objects.filter(role=UserRole.ADMIN, is_active=True):
        try:
            create_and_send_notification(
                user=admin,
                title='ร้านขอเปลี่ยนบัญชีรับเงิน',
                body=f'{merchant.name} ยื่นคำขอเปลี่ยนบัญชีธนาคาร รอตรวจสอบ',
                data={'type': 'BANK_CHANGE_PENDING', 'merchant_id': str(merchant.id), 'request_id': str(change.id)},
            )
        except Exception:  # แจ้งเตือนพลาดต้องไม่ทำให้คำขอล้มเหลว
            logger.exception('Cannot notify admin %s about bank change %s', admin.id, change.id)


@transaction.atomic
def submit_bank_change(merchant: Merchant, *, bank_name: str, bank_account_name: str, bank_account_number: str) -> MerchantBankChangeRequest:
    """ยื่นคำขอใหม่ — ใบที่รออยู่ก่อนหน้าถูกยกเลิกอัตโนมัติ (มีรอได้ทีละใบ)"""
    MerchantBankChangeRequest.objects.select_for_update().filter(
        merchant=merchant, status=BankChangeStatus.PENDING
    ).update(status=BankChangeStatus.CANCELLED)
    change = MerchantBankChangeRequest.objects.create(
        merchant=merchant,
        bank_name_encrypted=encrypt_bank_value(bank_name),
        bank_account_name_encrypted=encrypt_bank_value(bank_account_name),
        bank_account_number_encrypted=encrypt_bank_value(bank_account_number),
    )
    transaction.on_commit(lambda: _notify_admins_bank_change(merchant, change))
    return change


def _lock_pending(request_id) -> MerchantBankChangeRequest:
    change = MerchantBankChangeRequest.objects.select_for_update().select_related('merchant').filter(pk=request_id).first()
    if change is None:
        raise BankChangeError('BANK_CHANGE_NOT_FOUND', 'ไม่พบคำขอเปลี่ยนบัญชี')
    if change.status != BankChangeStatus.PENDING:
        raise BankChangeError('BANK_CHANGE_ALREADY_REVIEWED', 'คำขอนี้ถูกตรวจหรือยกเลิกไปแล้ว')
    return change


@transaction.atomic
def approve_bank_change(request_id, reviewer) -> MerchantBankChangeRequest:
    """อนุมัติ → คัดลอกบัญชีใหม่เข้าร้าน"""
    change = _lock_pending(request_id)
    merchant = Merchant.objects.select_for_update().get(pk=change.merchant_id)
    merchant.bank_name = decrypt_bank_value(change.bank_name_encrypted)
    merchant.bank_account_name = decrypt_bank_value(change.bank_account_name_encrypted)
    merchant.bank_account_number = decrypt_bank_value(change.bank_account_number_encrypted)
    merchant.save(update_fields=['bank_name', 'bank_account_name', 'bank_account_number', 'updated_at'])

    change.status = BankChangeStatus.APPROVED
    change.reviewer = reviewer
    change.reviewed_at = timezone.now()
    change.save(update_fields=['status', 'reviewer', 'reviewed_at'])
    logger.info('Bank change %s for merchant %s approved by %s', change.id, merchant.id, getattr(reviewer, 'id', None))
    _notify_merchant(merchant, 'อนุมัติบัญชีรับเงินใหม่แล้ว', 'ยอดขายรอบถัดไปจะโอนเข้าบัญชีใหม่', 'BANK_CHANGE_APPROVED')
    return change


@transaction.atomic
def reject_bank_change(request_id, reviewer, *, reason: str) -> MerchantBankChangeRequest:
    if not reason or len(reason.strip()) < 10:
        raise BankChangeError('REJECT_REASON_REQUIRED', 'ระบุเหตุผลอย่างน้อย 10 ตัวอักษร')
    change = _lock_pending(request_id)
    change.status = BankChangeStatus.REJECTED
    change.reviewer = reviewer
    change.reviewed_at = timezone.now()
    change.reject_reason = reason.strip()
    change.save(update_fields=['status', 'reviewer', 'reviewed_at', 'reject_reason'])
    logger.info('Bank change %s rejected by %s', change.id, getattr(reviewer, 'id', None))
    _notify_merchant(change.merchant, 'คำขอเปลี่ยนบัญชีไม่ผ่าน', reason.strip(), 'BANK_CHANGE_REJECTED')
    return change


def _notify_merchant(merchant: Merchant, title: str, body: str, kind: str) -> None:
    from apps.notifications.fcm import create_and_send_notification

    def send():
        try:
            create_and_send_notification(user=merchant.user, title=title, body=body, data={'type': kind})
        except Exception:
            logger.exception('Cannot notify merchant %s (%s)', merchant.id, kind)

    transaction.on_commit(send)
