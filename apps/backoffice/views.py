import math

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.serializers import AdminSlipSerializer
from apps.orders.models import Order
from apps.payments.models import SlipStatus, SlipTransaction
from apps.payments.services import SlipReviewError, approve_slip, reject_slip
from apps.users.permissions import IsAdminRole

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def _error(code, message, http_status, details=None):
    return Response({
        'success': False,
        'error_code': code,
        'message': message,
        'details': details or [],
    }, status=http_status)


def _parse_pagination(request):
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.query_params.get('page_size', DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError):
        page_size = DEFAULT_PAGE_SIZE
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    return page, page_size


class SlipListView(APIView):
    """GET /api/admin/v1/slips/ — คิวสลิปรอตรวจ (P1-09)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        slips = SlipTransaction.objects.select_related(
            'order', 'order__customer', 'order__merchant', 'reviewer'
        )

        status_filter = (request.query_params.get('status') or '').upper()
        if status_filter:
            if status_filter not in SlipStatus.values:
                return _error(
                    'INVALID_STATUS',
                    f'สถานะสลิปไม่ถูกต้อง: {status_filter}',
                    status.HTTP_400_BAD_REQUEST,
                )
            slips = slips.filter(status=status_filter)

        raw_date_from = request.query_params.get('date_from') or ''
        date_from = parse_date(raw_date_from) if raw_date_from else None
        if raw_date_from and not date_from:
            return _error('INVALID_DATE_FROM', 'รูปแบบ date_from ไม่ถูกต้อง (YYYY-MM-DD)', status.HTTP_400_BAD_REQUEST)
        if date_from:
            slips = slips.filter(created_at__date__gte=date_from)

        raw_date_to = request.query_params.get('date_to') or ''
        date_to = parse_date(raw_date_to) if raw_date_to else None
        if raw_date_to and not date_to:
            return _error('INVALID_DATE_TO', 'รูปแบบ date_to ไม่ถูกต้อง (YYYY-MM-DD)', status.HTTP_400_BAD_REQUEST)
        if date_to:
            slips = slips.filter(created_at__date__lte=date_to)

        keyword = (request.query_params.get('q') or '').strip()
        if keyword:
            from django.db.models import Q
            slips = slips.filter(
                Q(trans_ref__icontains=keyword)
                | Q(order__order_number__icontains=keyword)
                | Q(order__customer__display_name__icontains=keyword)
                | Q(order__customer__phone_number__icontains=keyword)
            )

        total = slips.count()
        page, page_size = _parse_pagination(request)
        total_pages = math.ceil(total / page_size) if total else 0
        offset = (page - 1) * page_size
        items = list(slips.order_by('-created_at')[offset:offset + page_size])

        pending_qs = SlipTransaction.objects.filter(status=SlipStatus.PENDING)
        pending_total = pending_qs.count()
        oldest_pending = pending_qs.order_by('created_at').values_list('created_at', flat=True).first()
        oldest_pending_minutes = (
            int((timezone.now() - oldest_pending).total_seconds() // 60) if oldest_pending else 0
        )

        serializer = AdminSlipSerializer(items, many=True, context={'request': request})
        return Response({
            'success': True,
            'data': serializer.data,
            'meta': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
                'pending_total': pending_total,
                'oldest_pending_minutes': oldest_pending_minutes,
            },
            'message': f'พบสลิปรอตรวจสอบ {pending_total} รายการ',
        })


class SlipDetailView(APIView):
    """GET /api/admin/v1/slips/<uuid>/ — รายละเอียดสลิป + ประวัติสลิป/สถานะของออเดอร์"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request, slip_id):
        slip = SlipTransaction.objects.select_related(
            'order', 'order__customer', 'order__merchant', 'reviewer'
        ).filter(pk=slip_id).first()
        if not slip:
            return _error('SLIP_NOT_FOUND', 'ไม่พบสลิปที่ระบุ', status.HTTP_404_NOT_FOUND)

        data = AdminSlipSerializer(slip, context={'request': request}).data
        history = SlipTransaction.objects.filter(order=slip.order).order_by('created_at')
        data['order_slip_history'] = [
            {
                'id': str(item.id),
                'status': item.status,
                'attempt_no': item.attempt_no,
                'trans_ref': item.trans_ref,
                'reject_reason': item.reject_reason,
                'created_at': item.created_at,
            }
            for item in history
        ]
        data['order']['status_logs'] = [
            {
                'from_status': log.from_status,
                'to_status': log.to_status,
                'role': log.role,
                'note': log.note,
                'created_at': log.created_at,
            }
            for log in slip.order.status_logs.order_by('created_at')
        ]

        return Response({
            'success': True,
            'data': data,
            'message': 'ดึงรายละเอียดสลิปสำเร็จ',
        })


def _review_error_response(error: SlipReviewError):
    http_status = {
        'SLIP_NOT_FOUND': status.HTTP_404_NOT_FOUND,
        'REJECT_REASON_REQUIRED': status.HTTP_400_BAD_REQUEST,
    }.get(error.code, status.HTTP_409_CONFLICT)
    return _error(error.code, str(error), http_status)


class SlipApproveView(APIView):
    """POST /api/admin/v1/slips/<uuid>/approve/ — อนุมัติสลิป → order PAID (P0-01/P1-09)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, slip_id):
        note = (request.data.get('note') or '').strip()
        try:
            slip = approve_slip(slip_id, request.user, note=note)
        except SlipReviewError as error:
            return _review_error_response(error)

        order = Order.objects.filter(pk=slip.order_id).first()
        return Response({
            'success': True,
            'data': {
                'slip_id': str(slip.id),
                'slip_status': slip.status,
                'order_id': str(slip.order_id),
                'order_status': order.status if order else None,
                'reviewed_at': slip.reviewed_at,
            },
            'message': 'อนุมัติสลิปและยืนยันการชำระเงินเรียบร้อยแล้ว',
        })


class SlipRejectView(APIView):
    """POST /api/admin/v1/slips/<uuid>/reject/ — ปฏิเสธสลิป (ต้องระบุ reason)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, slip_id):
        from django.conf import settings

        reason = (request.data.get('reason') or '').strip()
        try:
            slip = reject_slip(slip_id, request.user, reason=reason)
        except SlipReviewError as error:
            return _review_error_response(error)

        max_attempts = int(getattr(settings, 'SLIP_MAX_ATTEMPTS', 3))
        attempts_left = max(0, max_attempts - slip.attempt_no)
        order = Order.objects.filter(pk=slip.order_id).first()
        return Response({
            'success': True,
            'data': {
                'slip_id': str(slip.id),
                'slip_status': slip.status,
                'order_status': order.status if order else None,
                'attempts_left': attempts_left,
                'reject_reason': slip.reject_reason,
            },
            'message': 'ปฏิเสธสลิปและแจ้งลูกค้าแล้ว',
        })
