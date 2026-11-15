"""
หน้าแอดมิน: จัดการสาขาและไรเดอร์ (Module 33 · S-6)

ร้านเดียวหลายสาขา — แอดมิน (เจ้าของร้าน) สร้างบัญชีจอครัวของแต่ละสาขาและบัญชีไรเดอร์เอง
ใช้ฟังก์ชันชุดเดียวกับ `manage.py create_branch / create_rider` จึงตรวจข้อมูลเหมือนกันทุกทาง
ไม่มีการลบจริง: ปิดการใช้งาน = ล็อกอินไม่ได้ ข้อมูล/ออเดอร์เก่าอยู่ครบ
"""
import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.merchants.models import Merchant
from apps.riders.live_location import get_live_location
from apps.riders.models import RiderProfile
from apps.users.permissions import IsAdminRole
from apps.users.staff_accounts import (
    AccountInput,
    StaffAccountError,
    create_branch,
    create_rider,
    reset_staff_password,
    set_branch_active,
    set_rider_active,
)

logger = logging.getLogger(__name__)


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error_code': code, 'message': message, 'details': []}, status=http_status)


def _text(data, key):
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ''


def _bool(data, key):
    value = data.get(key)
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('1', 'true', 'yes', 'on')


def _account_from(data, *, default_display_name=''):
    """อ่านข้อมูลบัญชีจากฟอร์ม — คืน (AccountInput, error Response | None)"""
    use_existing = _bool(data, 'use_existing')
    password = data.get('password') or ''
    if not use_existing or password:
        if password != (data.get('password_confirm') or ''):
            return None, _error('PASSWORD_MISMATCH', 'รหัสผ่านทั้งสองช่องไม่ตรงกัน')
    account = AccountInput(
        email=_text(data, 'email'),
        display_name=_text(data, 'display_name') or default_display_name,
        phone_number=_text(data, 'phone_number'),
        password=password or None,
        use_existing=use_existing,
    )
    return account, None


def serialize_branch(merchant):
    return {
        'id': str(merchant.id),
        'name': merchant.name,
        'address': merchant.address,
        'phone_number': merchant.phone_number,
        'latitude': float(merchant.latitude),
        'longitude': float(merchant.longitude),
        'is_open': merchant.is_open,
        'is_active': merchant.user.is_active,
        'email': merchant.user.email,
        'display_name': merchant.user.display_name,
        'created_at': merchant.created_at,
    }


def serialize_rider(profile):
    live = get_live_location(profile.user_id)
    return {
        'id': str(profile.id),
        'display_name': profile.user.display_name,
        'email': profile.user.email,
        'phone_number': profile.user.phone_number or '',
        'vehicle_plate': profile.vehicle_plate,
        'is_online': profile.is_online,
        'is_active': profile.user.is_active,
        'last_location_at': live.updated_at if live else None,
        'created_at': profile.created_at,
    }


class AdminBranchListView(APIView):
    """GET รายการสาขา · POST สร้างสาขาใหม่ (= บัญชีจอครัว 1 บัญชี)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        branches = Merchant.objects.select_related('user').order_by('created_at')
        return Response({'success': True, 'data': [serialize_branch(item) for item in branches]})

    def post(self, request):
        data = request.data
        name = _text(data, 'name')
        account, problem = _account_from(data, default_display_name=name)
        if problem:
            return problem
        try:
            branch = create_branch(
                account,
                name=name,
                address=_text(data, 'address'),
                latitude=data.get('latitude'),
                longitude=data.get('longitude'),
                description=_text(data, 'description'),
            )
        except StaffAccountError as error:
            return _error('STAFF_ACCOUNT_INVALID', str(error))
        logger.info('admin %s created branch %s (%s)', request.user.pk, branch.pk, branch.user.email)
        return Response({'success': True, 'data': serialize_branch(branch)}, status=status.HTTP_201_CREATED)


class AdminRiderListView(APIView):
    """GET รายการไรเดอร์ · POST สร้างบัญชีไรเดอร์ที่ใช้ได้ทันที"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        riders = RiderProfile.objects.select_related('user').order_by('created_at')
        return Response({'success': True, 'data': [serialize_rider(item) for item in riders]})

    def post(self, request):
        data = request.data
        account, problem = _account_from(data)
        if problem:
            return problem
        try:
            rider = create_rider(account, vehicle_plate=_text(data, 'vehicle_plate'))
        except StaffAccountError as error:
            return _error('STAFF_ACCOUNT_INVALID', str(error))
        logger.info('admin %s created rider %s (%s)', request.user.pk, rider.pk, rider.user.email)
        return Response({'success': True, 'data': serialize_rider(rider)}, status=status.HTTP_201_CREATED)


class _StaffDetailBase(APIView):
    """PATCH {is_active} = เปิด/ปิดการใช้งาน · POST .../password/ = ตั้งรหัสผ่านใหม่"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'
    model = None
    set_active = None
    serialize = None
    not_found_message = ''

    def _get(self, pk):
        return self.model.objects.select_related('user').filter(pk=pk).first()

    def patch(self, request, pk):
        item = self._get(pk)
        if item is None:
            return _error('NOT_FOUND', self.not_found_message, status.HTTP_404_NOT_FOUND)
        if 'is_active' not in request.data:
            return _error('NOTHING_TO_UPDATE', 'ส่ง is_active มาด้วย')
        try:
            type(self).set_active(item, _bool(request.data, 'is_active'))
        except StaffAccountError as error:
            return _error('STAFF_ACCOUNT_INVALID', str(error), status.HTTP_409_CONFLICT)
        item.user.refresh_from_db()
        logger.info('admin %s set %s %s active=%s', request.user.pk, self.model.__name__, item.pk, item.user.is_active)
        return Response({'success': True, 'data': type(self).serialize(item)})


class AdminBranchDetailView(_StaffDetailBase):
    model = Merchant
    set_active = staticmethod(set_branch_active)
    serialize = staticmethod(serialize_branch)
    not_found_message = 'ไม่พบสาขานี้'


class AdminRiderDetailView(_StaffDetailBase):
    model = RiderProfile
    set_active = staticmethod(set_rider_active)
    serialize = staticmethod(serialize_rider)
    not_found_message = 'ไม่พบไรเดอร์คนนี้'


class _StaffPasswordBase(APIView):
    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'
    model = None
    not_found_message = ''

    def post(self, request, pk):
        item = self.model.objects.select_related('user').filter(pk=pk).first()
        if item is None:
            return _error('NOT_FOUND', self.not_found_message, status.HTTP_404_NOT_FOUND)
        password = request.data.get('password') or ''
        if password != (request.data.get('password_confirm') or ''):
            return _error('PASSWORD_MISMATCH', 'รหัสผ่านทั้งสองช่องไม่ตรงกัน')
        try:
            reset_staff_password(item.user, password)
        except StaffAccountError as error:
            return _error('STAFF_ACCOUNT_INVALID', str(error))
        logger.info('admin %s reset password of %s %s', request.user.pk, self.model.__name__, item.pk)
        return Response({'success': True, 'message': 'ตั้งรหัสผ่านใหม่แล้ว เครื่องที่ล็อกอินค้างไว้ต้องล็อกอินใหม่'})


class AdminBranchPasswordView(_StaffPasswordBase):
    model = Merchant
    not_found_message = 'ไม่พบสาขานี้'


class AdminRiderPasswordView(_StaffPasswordBase):
    model = RiderProfile
    not_found_message = 'ไม่พบไรเดอร์คนนี้'
