"""
สร้างบัญชีสาขา (ร้าน) และไรเดอร์โดยแอดมิน — Module 33 (ร้านเดียว ไม่ใช่ marketplace)

แทนขั้นตอนสมัคร + ส่งเอกสาร + รออนุมัติ: เจ้าของร้านสร้างบัญชีให้เองผ่าน
`manage.py create_branch` / `manage.py create_rider` (และหน้าแอดมินในอนาคตเรียกฟังก์ชันชุดนี้ได้เลย)
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.contrib.auth.password_validation import validate_password
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.users.models import User, UserRole

MIN_PASSWORD_LENGTH = 12  # เท่ากับ EmailRegistrationSerializer

# บัญชีเดิมที่ยอมให้แปลงเป็นสาขา/ไรเดอร์ได้ (ไม่แตะบัญชีแอดมินหรือบัญชีที่มีบทบาทอื่นอยู่แล้ว)
CONVERTIBLE_ROLES = {UserRole.UNASSIGNED, UserRole.CUSTOMER}


class StaffAccountError(Exception):
    """ข้อมูลไม่ถูกต้อง หรือสร้างบัญชีไม่ได้ — ข้อความเป็นภาษาไทยสำหรับแสดงผล"""


@dataclass(frozen=True)
class AccountInput:
    email: str
    display_name: str
    phone_number: str
    password: str | None  # None = ใช้บัญชีเดิม (use_existing) ไม่เปลี่ยนรหัสผ่าน
    use_existing: bool = False


def parse_coordinates(lat, lng) -> tuple[Decimal, Decimal]:
    """ตรวจพิกัดจริง — ไม่รับ 0,0 และค่าที่อยู่นอกช่วง (ไม่มีพิกัดสำรอง)"""
    try:
        lat_value = Decimal(str(lat))
        lng_value = Decimal(str(lng))
    except (InvalidOperation, TypeError, ValueError):
        raise StaffAccountError('พิกัดต้องเป็นตัวเลข เช่น --lat 12.9236 --lng 100.8825')
    if not (-90 <= lat_value <= 90) or not (-180 <= lng_value <= 180):
        raise StaffAccountError('พิกัดอยู่นอกช่วง (latitude -90..90, longitude -180..180)')
    if lat_value == 0 and lng_value == 0:
        raise StaffAccountError('พิกัด 0,0 ไม่ใช่ตำแหน่งจริง กรุณาใส่พิกัดของสาขา')
    return lat_value.quantize(Decimal('0.0000001')), lng_value.quantize(Decimal('0.0000001'))


def _validate_new_password(password: str, user: User) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise StaffAccountError(f'รหัสผ่านต้องยาวอย่างน้อย {MIN_PASSWORD_LENGTH} ตัวอักษร')
    try:
        validate_password(password, user=user)
    except ValidationError as error:
        raise StaffAccountError(' '.join(error.messages)) from error


def _prepare_user(account: AccountInput, role: str) -> User:
    """สร้างผู้ใช้ใหม่ หรือแปลงบัญชีเดิม (เมื่อสั่ง use_existing) ให้เป็น role ที่กำหนด"""
    email = (account.email or '').strip().lower()
    if not email or '@' not in email:
        raise StaffAccountError('กรุณาระบุอีเมลสำหรับเข้าสู่ระบบ')
    display_name = (account.display_name or '').strip()
    if not display_name:
        raise StaffAccountError('กรุณาระบุชื่อที่แสดง')

    existing = User.objects.filter(email__iexact=email).first()
    if existing and not account.use_existing:
        raise StaffAccountError(
            f'มีบัญชี {email} อยู่แล้ว — ถ้าต้องการใช้บัญชีนี้ให้เพิ่ม --use-existing'
        )
    if existing:
        if existing.role not in CONVERTIBLE_ROLES:
            raise StaffAccountError(
                f'บัญชี {email} มีบทบาท {existing.role} อยู่แล้ว — ใช้อีเมลอื่นสำหรับบัญชีนี้'
            )
        user = existing
    else:
        if account.password is None:
            raise StaffAccountError('บัญชีใหม่ต้องตั้งรหัสผ่าน')
        user = User(email=email)

    if account.password is not None:
        _validate_new_password(account.password, user)
        user.set_password(account.password)

    user.display_name = display_name
    if account.phone_number:
        user.phone_number = account.phone_number.strip()
    user.role = role
    user.is_active = True
    user.save()
    return user


@transaction.atomic
def create_branch(
    account: AccountInput,
    *,
    name: str,
    address: str,
    latitude,
    longitude,
    description: str = '',
    image_url: str = '',
    bank_name: str = '',
    bank_account_name: str = '',
    bank_account_number: str = '',
):
    """สร้างสาขาใหม่ 1 สาขา = บัญชีจอครัว 1 บัญชี (Merchant ผูกกับ User แบบ 1:1)"""
    from apps.merchants.models import Merchant
    from apps.users.services import DEFAULT_STOREFRONT_IMAGE

    branch_name = (name or '').strip()
    if not branch_name:
        raise StaffAccountError('กรุณาระบุชื่อสาขา')
    branch_address = (address or '').strip()
    if not branch_address:
        raise StaffAccountError('กรุณาระบุที่อยู่สาขา')
    if not (account.phone_number or '').strip():
        raise StaffAccountError('กรุณาระบุเบอร์โทรของสาขา')
    lat, lng = parse_coordinates(latitude, longitude)

    user = _prepare_user(account, UserRole.MERCHANT)
    if Merchant.objects.filter(user=user).exists():
        raise StaffAccountError(f'บัญชี {user.email} มีสาขาผูกอยู่แล้ว')

    return Merchant.objects.create(
        user=user,
        name=branch_name,
        description=(description or '').strip() or None,
        image_url=(image_url or '').strip() or DEFAULT_STOREFRONT_IMAGE,
        phone_number=account.phone_number.strip(),
        address=branch_address,
        latitude=lat,
        longitude=lng,
        location=Point(float(lng), float(lat), srid=4326),
        is_open=False,  # เปิดร้านเองจากจอครัวเมื่อพร้อม
        bank_name=(bank_name or '').strip(),
        bank_account_name=(bank_account_name or '').strip(),
        bank_account_number=(bank_account_number or '').strip(),
    )


@transaction.atomic
def create_rider(account: AccountInput, *, vehicle_plate: str):
    """สร้างบัญชีไรเดอร์ที่ใช้ได้ทันที (ไม่ต้องส่งเอกสาร/รออนุมัติ)"""
    from apps.riders.models import RiderProfile

    plate = (vehicle_plate or '').strip()
    if not plate:
        raise StaffAccountError('กรุณาระบุทะเบียนรถ')
    if not (account.phone_number or '').strip():
        raise StaffAccountError('กรุณาระบุเบอร์โทรไรเดอร์ (ลูกค้า/ร้านใช้โทรหา)')

    user = _prepare_user(account, UserRole.RIDER)
    if RiderProfile.objects.filter(user=user).exists():
        raise StaffAccountError(f'บัญชี {user.email} เป็นไรเดอร์อยู่แล้ว')

    return RiderProfile.objects.create(user=user, vehicle_plate=plate, is_online=False)
