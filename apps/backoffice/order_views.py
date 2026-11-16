"""
API หลังบ้าน: ออเดอร์ (B2) + บันทึกการแก้ไขของแอดมิน (B1)
"""
import math
import uuid

from django.db.models import Count, Q
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.audit import ACTION_LABELS, serialize_audit_log
from apps.backoffice.data_views import proof_file_url
from apps.backoffice.models import AdminAuditLog
from apps.backoffice.order_actions import (
    STATUS_LABELS,
    AdminOrderError,
    admin_advance_status,
    admin_assign_rider,
    admin_cancel_order,
    allowed_actions,
)
from apps.orders.models import Order, OrderStatus
from apps.users.permissions import IsAdminRole

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20

ERROR_STATUS = {
    'ORDER_NOT_FOUND': status.HTTP_404_NOT_FOUND,
    'RIDER_NOT_FOUND': status.HTTP_404_NOT_FOUND,
    'REASON_REQUIRED': status.HTTP_400_BAD_REQUEST,
}


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error_code': code, 'message': message, 'details': []}, status=http_status)


def _action_error(error: AdminOrderError):
    return _error(error.code, str(error), ERROR_STATUS.get(error.code, status.HTTP_409_CONFLICT))


def _page(request):
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(request.query_params.get('page_size', DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        size = DEFAULT_PAGE_SIZE
    return page, max(1, min(size, MAX_PAGE_SIZE))


def _person(user, *, with_contact=True):
    if user is None:
        return None
    data = {'id': str(user.pk), 'name': user.display_name}
    if with_contact:
        data.update({'email': user.email, 'phone': user.phone_number or ''})
    return data


def serialize_order_row(order: Order) -> dict:
    return {
        'id': str(order.id),
        'order_number': order.order_number,
        'status': order.status,
        'status_label': STATUS_LABELS.get(order.status, order.status),
        'total_amount': str(order.total_amount),
        'customer': _person(order.customer, with_contact=False),
        'merchant': {'id': str(order.merchant_id), 'name': order.merchant.name},
        'rider': _person(order.rider, with_contact=False),
        'item_count': getattr(order, 'item_count', None),
        'created_at': order.created_at,
        'updated_at': order.updated_at,
    }


class AdminOrderListView(APIView):
    """GET /api/admin/v1/orders/ — ค้นหา/กรองออเดอร์ทั้งหมด"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        params = request.query_params
        orders = Order.objects.select_related('customer', 'merchant', 'rider')

        keyword = (params.get('q') or '').strip()
        if keyword:
            orders = orders.filter(
                Q(order_number__icontains=keyword)
                | Q(customer__display_name__icontains=keyword)
                | Q(customer__email__icontains=keyword)
                | Q(customer__phone_number__icontains=keyword)
                | Q(delivery_address__icontains=keyword)
            )
        if params.get('merchant'):
            orders = orders.filter(merchant_id=params['merchant'])
        if params.get('rider'):
            orders = orders.filter(rider_id=params['rider'])

        for key, lookup in (('date_from', 'created_at__date__gte'), ('date_to', 'created_at__date__lte')):
            raw = params.get(key) or ''
            if raw:
                value = parse_date(raw)
                if value is None:
                    return _error('INVALID_DATE', f'รูปแบบ {key} ไม่ถูกต้อง (YYYY-MM-DD)')
                orders = orders.filter(**{lookup: value})

        # จำนวนต่อสถานะ (ตามตัวกรองอื่น ไม่รวมตัวกรองสถานะ) — ใช้แสดงบนแท็บ
        counts = {row['status']: row['n'] for row in orders.order_by().values('status').annotate(n=Count('id'))}

        statuses = [value.strip().upper() for value in (params.get('status') or '').split(',') if value.strip()]
        invalid = [value for value in statuses if value not in OrderStatus.values]
        if invalid:
            return _error('INVALID_STATUS', f'สถานะไม่ถูกต้อง: {", ".join(invalid)}')
        if statuses:
            orders = orders.filter(status__in=statuses)

        total = orders.count()
        page, size = _page(request)
        rows = orders.annotate(item_count=Count('items')).order_by('-created_at')[(page - 1) * size: page * size]
        return Response({
            'success': True,
            'data': [serialize_order_row(order) for order in rows],
            'meta': {
                'page': page,
                'page_size': size,
                'total': total,
                'total_pages': max(1, math.ceil(total / size)),
                'status_counts': {value: counts.get(value, 0) for value in OrderStatus.values},
                'status_labels': STATUS_LABELS,
            },
        })


class AdminOrderDetailView(APIView):
    """GET /api/admin/v1/orders/<uuid>/ — รายละเอียดครบ + ประวัติ + ปุ่มที่ทำได้"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request, order_id):
        order = (
            Order.objects.select_related('customer', 'merchant', 'rider', 'cancelled_by')
            .prefetch_related('items', 'status_logs__actor', 'slip_transactions')
            .filter(pk=order_id)
            .first()
        )
        if order is None:
            return _error('ORDER_NOT_FOUND', 'ไม่พบออเดอร์นี้', status.HTTP_404_NOT_FOUND)

        rider = None
        if order.rider:
            profile = getattr(order.rider, 'rider_profile', None)
            rider = {**_person(order.rider), 'vehicle_plate': profile.vehicle_plate if profile else ''}
        proof = getattr(order, 'delivery_proof', None)  # ไม่มี = None (RelatedObjectDoesNotExist เป็น AttributeError)

        audit = AdminAuditLog.objects.filter(target_type='order', target_id=str(order.pk)).order_by('-created_at')[:50]
        data = {
            **serialize_order_row(order),
            'customer': _person(order.customer),
            'merchant': {
                'id': str(order.merchant_id),
                'name': order.merchant.name,
                'phone': order.merchant.phone_number,
                'address': order.merchant.address,
            },
            'rider': rider,
            'delivery': {
                'address': order.delivery_address,
                'latitude': float(order.delivery_latitude),
                'longitude': float(order.delivery_longitude),
                'distance_km': str(order.delivery_distance_km),
            },
            'note_to_merchant': order.note_to_merchant or '',
            'money': {
                'subtotal': str(order.subtotal),
                'delivery_fee': str(order.delivery_fee),
                'total_amount': str(order.total_amount),
                'rider_delivery_fee': str(order.rider_delivery_fee),
                'platform_fee': str(order.platform_fee),
                'platform_delivery_fee': str(order.platform_delivery_fee),
            },
            'items': [
                {
                    'name': item.item_name,
                    'quantity': item.quantity,
                    'unit_price': str(item.unit_price),
                    'total_price': str(item.total_price),
                    'options': item.selected_options,
                }
                for item in order.items.all()
            ],
            'status_logs': [
                {
                    'from_status': log.from_status,
                    'to_status': log.to_status,
                    'to_status_label': STATUS_LABELS.get(log.to_status, log.to_status),
                    'role': log.role,
                    'actor': log.actor.display_name if log.actor else None,
                    'note': log.note or '',
                    'created_at': log.created_at,
                }
                for log in sorted(order.status_logs.all(), key=lambda entry: entry.created_at)
            ],
            'slips': [
                {
                    'id': str(slip.id),
                    'status': slip.status,
                    'amount': str(slip.amount),
                    'attempt_no': slip.attempt_no,
                    'reject_reason': slip.reject_reason or '',
                    'created_at': slip.created_at,
                }
                for slip in sorted(order.slip_transactions.all(), key=lambda entry: entry.created_at)
            ],
            'delivery_proof': {
                'created_at': proof.created_at,
                'recipient_confirmed': proof.recipient_confirmed,
                'proof_url': proof_file_url(request, proof, 'proof'),
                'signature_url': proof_file_url(request, proof, 'signature'),
            } if proof else None,
            'paid_at': order.paid_at,
            'completed_at': order.completed_at,
            'cancelled_reason': order.cancelled_reason or '',
            'cancelled_by': order.cancelled_by.display_name if order.cancelled_by else None,
            'actions': allowed_actions(order),
            'audit_logs': [serialize_audit_log(entry) for entry in audit],
        }
        return Response({'success': True, 'data': data})


class _OrderActionView(APIView):
    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def respond(self, order, message, extra=None):
        order.refresh_from_db()
        return Response({
            'success': True,
            'message': message,
            'data': {'id': str(order.id), 'status': order.status, 'status_label': STATUS_LABELS.get(order.status), **(extra or {})},
        })


class AdminOrderCancelView(_OrderActionView):
    """POST /orders/<uuid>/cancel/ {reason}"""

    def post(self, request, order_id):
        try:
            order, refund_needed = admin_cancel_order(order_id, request.user, request.data.get('reason'), request=request)
        except AdminOrderError as error:
            return _action_error(error)
        message = 'ยกเลิกออเดอร์แล้ว' + (' — ลูกค้าจ่ายเงินแล้ว ต้องโอนคืนลูกค้าเอง' if refund_needed else '')
        return self.respond(order, message, {'refund_needed': refund_needed})


class AdminOrderStatusView(_OrderActionView):
    """POST /orders/<uuid>/status/ {to_status, note}"""

    def post(self, request, order_id):
        to_status = str(request.data.get('to_status') or '').upper()
        try:
            order = admin_advance_status(order_id, request.user, to_status, request.data.get('note') or '', request=request)
        except AdminOrderError as error:
            return _action_error(error)
        return self.respond(order, f'เปลี่ยนสถานะเป็น "{STATUS_LABELS.get(order.status)}" แล้ว')


class AdminOrderAssignRiderView(_OrderActionView):
    """POST /orders/<uuid>/assign-rider/ {rider_id (RiderProfile id), note}"""

    def post(self, request, order_id):
        try:
            rider_id = uuid.UUID(str(request.data.get('rider_id') or ''))
        except ValueError:
            return _error('RIDER_REQUIRED', 'เลือกไรเดอร์ก่อน')
        try:
            order = admin_assign_rider(order_id, request.user, rider_id, request.data.get('note') or '', request=request)
        except AdminOrderError as error:
            return _action_error(error)
        return self.respond(order, 'มอบหมายไรเดอร์แล้ว')


class AdminAuditLogListView(APIView):
    """GET /api/admin/v1/audit-logs/ — บันทึกการแก้ไขของแอดมินทั้งหมด (ดูอย่างเดียว)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        params = request.query_params
        logs = AdminAuditLog.objects.all()
        for key in ('target_type', 'target_id', 'action'):
            if params.get(key):
                logs = logs.filter(**{key: params[key]})
        keyword = (params.get('q') or '').strip()
        if keyword:
            logs = logs.filter(Q(target_label__icontains=keyword) | Q(actor_label__icontains=keyword) | Q(note__icontains=keyword))
        total = logs.count()
        page, size = _page(request)
        rows = logs.order_by('-created_at')[(page - 1) * size: page * size]
        return Response({
            'success': True,
            'data': [serialize_audit_log(entry) for entry in rows],
            'meta': {
                'page': page,
                'page_size': size,
                'total': total,
                'total_pages': max(1, math.ceil(total / size)),
                'action_labels': ACTION_LABELS,
            },
        })
