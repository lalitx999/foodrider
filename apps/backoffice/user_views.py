"""
หลังบ้าน: ผู้ใช้/ลูกค้า (Module 32 เฟส B · B5)

กติกากันพลาด:
- แอดมินแก้สิทธิ์/ปิดบัญชีตัวเองไม่ได้ และถอดหรือปิดแอดมินคนสุดท้ายที่ใช้งานอยู่ไม่ได้
- สิทธิ์ร้าน/ไรเดอร์จัดการที่หน้า "สาขาและไรเดอร์" (ต้องมีข้อมูลสาขา/ทะเบียนรถ) — หน้านี้สลับได้แค่ ลูกค้า ⇄ แอดมิน
- ปิดบัญชีร้าน/ไรเดอร์ใช้กติกาเดียวกับหน้าสาขาและไรเดอร์ (มีออเดอร์ค้าง = ปิดไม่ได้)
- ไม่มีการลบผู้ใช้ (ออเดอร์อ้างอิงแบบ RESTRICT)
"""
import math
import re

from django.db import transaction
from django.db.models import Count, Q, Sum
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.audit import diff, record_admin_action
from apps.backoffice.order_views import serialize_order_row
from apps.orders.models import Order, OrderStatus
from apps.users.models import User, UserRole
from apps.users.permissions import IsAdminRole
from apps.users.staff_accounts import (
    StaffAccountError,
    _revoke_sessions,
    _validate_new_password,
    set_branch_active,
    set_rider_active,
)

ROLE_LABELS = {
    UserRole.UNASSIGNED: 'ยังไม่เลือกบทบาท',
    UserRole.CUSTOMER: 'ลูกค้า',
    UserRole.MERCHANT: 'สาขา (จอครัว)',
    UserRole.RIDER: 'ไรเดอร์',
    UserRole.ADMIN: 'แอดมิน',
}
SWITCHABLE_ROLES = {UserRole.UNASSIGNED, UserRole.CUSTOMER, UserRole.ADMIN}
PHONE_PATTERN = re.compile(r'^[0-9+\-\s]{9,15}$')


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error_code': code, 'message': message, 'details': []}, status=http_status)


def _bool(raw) -> bool:
    return raw if isinstance(raw, bool) else str(raw).lower() in ('1', 'true', 'yes', 'on')


def _page(request):
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    return page, 20


def serialize_user_row(user: User) -> dict:
    return {
        'id': str(user.id),
        'display_name': user.display_name,
        'email': user.email or '',
        'phone_number': user.phone_number or '',
        'role': user.role,
        'role_label': ROLE_LABELS.get(user.role, user.role),
        'is_active': user.is_active,
        'login_method': 'Google' if user.google_user_id else 'อีเมล',
        'order_count': getattr(user, 'order_count', None),
        'created_at': user.created_at,
        'last_login': user.last_login,
    }


def _other_active_admins(user: User) -> int:
    return User.objects.filter(role=UserRole.ADMIN, is_active=True).exclude(pk=user.pk).count()


class AdminUserListView(APIView):
    """GET /users/?role=&q=&active=&page="""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        params = request.query_params
        users = User.objects.all()
        role = (params.get('role') or '').upper()
        if role:
            if role not in UserRole.values:
                return _error('INVALID_ROLE', f'บทบาทไม่ถูกต้อง: {role}')
            users = users.filter(role=role)
        if params.get('active') in ('true', 'false'):
            users = users.filter(is_active=params['active'] == 'true')
        keyword = (params.get('q') or '').strip()
        if keyword:
            users = users.filter(Q(display_name__icontains=keyword) | Q(email__icontains=keyword) | Q(phone_number__icontains=keyword))

        counts = {row['role']: row['n'] for row in User.objects.order_by().values('role').annotate(n=Count('id'))}
        total = users.count()
        page, size = _page(request)
        rows = users.annotate(order_count=Count('customer_orders')).order_by('-created_at')[(page - 1) * size: page * size]
        return Response({
            'success': True,
            'data': [serialize_user_row(user) for user in rows],
            'meta': {
                'page': page,
                'total': total,
                'total_pages': max(1, math.ceil(total / size)),
                'role_counts': {value: counts.get(value, 0) for value in UserRole.values},
                'role_labels': ROLE_LABELS,
            },
        })


def _user_detail(user: User) -> dict:
    data = serialize_user_row(user)
    profile = getattr(user, 'customer_profile', None)
    orders = Order.objects.filter(customer=user)
    stats = orders.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status=OrderStatus.COMPLETED)),
        cancelled=Count('id', filter=Q(status=OrderStatus.CANCELLED)),
        spent=Sum('total_amount', filter=Q(status=OrderStatus.COMPLETED)),
    )
    merchant = getattr(user, 'merchant_profile', None)
    rider = getattr(user, 'rider_profile', None)
    data.update({
        'customer_profile': {
            'default_delivery_address': profile.default_delivery_address,
            'latitude': float(profile.delivery_latitude) if profile.delivery_latitude is not None else None,
            'longitude': float(profile.delivery_longitude) if profile.delivery_longitude is not None else None,
        } if profile else None,
        'stats': {
            'orders': stats['total'] or 0,
            'completed': stats['completed'] or 0,
            'cancelled': stats['cancelled'] or 0,
            'spent': str(stats['spent'] or '0.00'),
        },
        'recent_orders': [serialize_order_row(order) for order in orders.select_related('customer', 'merchant', 'rider').order_by('-created_at')[:10]],
        'branch': {'id': str(merchant.id), 'name': merchant.name} if merchant else None,
        'rider': {'id': str(rider.id), 'vehicle_plate': rider.vehicle_plate} if rider else None,
        'can_switch_role': user.role in SWITCHABLE_ROLES,
    })
    return data


class AdminUserDetailView(APIView):
    """GET /users/<id>/ · PATCH {display_name?, phone_number?, is_active?}"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def _get(self, user_id):
        return User.objects.filter(pk=user_id).first()

    def get(self, request, user_id):
        user = self._get(user_id)
        if user is None:
            return _error('USER_NOT_FOUND', 'ไม่พบผู้ใช้นี้', status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': _user_detail(user)})

    def patch(self, request, user_id):
        user = self._get(user_id)
        if user is None:
            return _error('USER_NOT_FOUND', 'ไม่พบผู้ใช้นี้', status.HTTP_404_NOT_FOUND)
        data = request.data
        before = {'display_name': user.display_name, 'phone_number': user.phone_number or ''}

        if 'display_name' in data:
            name = str(data.get('display_name') or '').strip()
            if not name or len(name) > 255:
                return _error('INVALID_NAME', 'ชื่อต้องมี 1–255 ตัวอักษร')
            user.display_name = name
        if 'phone_number' in data:
            phone = str(data.get('phone_number') or '').strip()
            if phone and not PHONE_PATTERN.match(phone):
                return _error('INVALID_PHONE', 'เบอร์โทรไม่ถูกต้อง')
            user.phone_number = phone or None

        with transaction.atomic():
            user.save(update_fields=['display_name', 'phone_number', 'updated_at'])
            changes = diff(before, {'display_name': user.display_name, 'phone_number': user.phone_number or ''})
            if changes:
                record_admin_action(request.user, 'user.update', target_type='user', target_id=user.pk,
                                    target_label=user.display_name, changes=changes, request=request)

            if 'is_active' in data:
                active = _bool(data.get('is_active'))
                if active != user.is_active:
                    problem = self._toggle_active(request, user, active)
                    if problem:
                        transaction.set_rollback(True)
                        return problem
        user.refresh_from_db()
        return Response({'success': True, 'data': _user_detail(user)})

    def _toggle_active(self, request, user: User, active: bool):
        if user.pk == request.user.pk:
            return _error('CANNOT_CHANGE_SELF', 'ปิดบัญชีตัวเองไม่ได้', status.HTTP_409_CONFLICT)
        if not active and user.role == UserRole.ADMIN and _other_active_admins(user) == 0:
            return _error('LAST_ADMIN', 'ปิดแอดมินคนสุดท้ายไม่ได้', status.HTTP_409_CONFLICT)
        try:
            merchant = getattr(user, 'merchant_profile', None)
            rider = getattr(user, 'rider_profile', None)
            if user.role == UserRole.MERCHANT and merchant:
                set_branch_active(merchant, active)
            elif user.role == UserRole.RIDER and rider:
                set_rider_active(rider, active)
            else:
                user.is_active = active
                user.save(update_fields=['is_active'])
                if not active:
                    _revoke_sessions(user)
        except StaffAccountError as error:
            return _error('STAFF_ACCOUNT_INVALID', str(error), status.HTTP_409_CONFLICT)
        record_admin_action(
            request.user, 'user.activate' if active else 'user.deactivate', target_type='user', target_id=user.pk,
            target_label=user.display_name, changes={'is_active': {'from': not active, 'to': active}}, request=request,
        )
        return None


class AdminUserRoleView(APIView):
    """POST /users/<id>/role/ {role: CUSTOMER | ADMIN}"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, user_id):
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return _error('USER_NOT_FOUND', 'ไม่พบผู้ใช้นี้', status.HTTP_404_NOT_FOUND)
        role = str(request.data.get('role') or '').upper()
        if role not in (UserRole.CUSTOMER, UserRole.ADMIN):
            return _error('INVALID_ROLE', 'เปลี่ยนได้เฉพาะ "ลูกค้า" หรือ "แอดมิน" — สาขา/ไรเดอร์ จัดการที่หน้าสาขาและไรเดอร์')
        if user.pk == request.user.pk:
            return _error('CANNOT_CHANGE_SELF', 'เปลี่ยนสิทธิ์ตัวเองไม่ได้', status.HTTP_409_CONFLICT)
        if user.role not in SWITCHABLE_ROLES:
            return _error('ROLE_LOCKED', f'บัญชีนี้เป็น{ROLE_LABELS[user.role]} — จัดการที่หน้าสาขาและไรเดอร์', status.HTTP_409_CONFLICT)
        if role == user.role:
            return _error('SAME_ROLE', f'บัญชีนี้เป็น{ROLE_LABELS[role]}อยู่แล้ว', status.HTTP_409_CONFLICT)
        if user.role == UserRole.ADMIN and _other_active_admins(user) == 0:
            return _error('LAST_ADMIN', 'ถอดแอดมินคนสุดท้ายไม่ได้', status.HTTP_409_CONFLICT)
        if role == UserRole.ADMIN and not user.is_active:
            return _error('USER_INACTIVE', 'เปิดการใช้งานบัญชีก่อนตั้งเป็นแอดมิน', status.HTTP_409_CONFLICT)

        before = user.role
        with transaction.atomic():
            user.role = role
            user.is_staff = role == UserRole.ADMIN  # ตรงกับ manage.py promote_admin
            user.save(update_fields=['role', 'is_staff', 'updated_at'])
            _revoke_sessions(user)  # สิทธิ์ใหม่มีผลเมื่อล็อกอินใหม่
            record_admin_action(
                request.user, 'user.role', target_type='user', target_id=user.pk, target_label=user.display_name,
                changes={'role': {'from': ROLE_LABELS.get(before, before), 'to': ROLE_LABELS[role]}}, request=request,
            )
        return Response({'success': True, 'data': _user_detail(user), 'message': f'เปลี่ยนเป็น{ROLE_LABELS[role]}แล้ว — มีผลเมื่อล็อกอินใหม่'})


class AdminUserPasswordView(APIView):
    """POST /users/<id>/password/ {password, password_confirm} — ไม่ใช้กับบัญชีแอดมิน"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, user_id):
        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return _error('USER_NOT_FOUND', 'ไม่พบผู้ใช้นี้', status.HTTP_404_NOT_FOUND)
        if user.role == UserRole.ADMIN:
            return _error('ADMIN_PASSWORD', 'ตั้งรหัสผ่านแอดมินจากหน้านี้ไม่ได้', status.HTTP_409_CONFLICT)
        password = request.data.get('password') or ''
        if password != (request.data.get('password_confirm') or ''):
            return _error('PASSWORD_MISMATCH', 'รหัสผ่านทั้งสองช่องไม่ตรงกัน')
        try:
            _validate_new_password(password, user)
        except StaffAccountError as error:
            return _error('WEAK_PASSWORD', str(error))
        with transaction.atomic():
            user.set_password(password)
            user.save(update_fields=['password'])
            _revoke_sessions(user)
            record_admin_action(request.user, 'user.password_reset', target_type='user', target_id=user.pk,
                                target_label=user.display_name, request=request)
        return Response({'success': True, 'message': 'ตั้งรหัสผ่านใหม่แล้ว เครื่องที่ล็อกอินค้างไว้ต้องล็อกอินใหม่'})
