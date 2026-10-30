from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils.text import get_valid_filename
from uuid import uuid4
from apps.orders.models import Order, OrderStatus
from apps.merchants.models import Merchant
from apps.orders.serializers import (
    OrderQuoteRequestSerializer,
    CreateOrderSerializer,
    UploadSlipSerializer,
    OrderDetailSerializer
)
from apps.orders.services import (
    calculate_order_quote,
    create_order_transaction,
    transition_order,
    InvalidTransition,
    OrderCalculationError
)
from apps.payments.models import SlipStatus
from apps.payments.services import (
    verify_and_process_order_slip,
    SlipVerificationError,
    SlipReviewError,
)
from apps.payments.storage import slip_storage
from apps.users.permissions import HasMerchantProfile, HasCustomerProfile
from apps.notifications.fcm import create_and_send_notification
from apps.payments.promptpay import create_promptpay_qr
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime


# สถานะที่ร้านค้าเปลี่ยนได้เอง (ห้ามร้านตั้ง PAID — P0-03)
MERCHANT_ALLOWED_TRANSITIONS = {
    OrderStatus.PAID: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY_FOR_PICKUP, OrderStatus.CANCELLED},
}


class OrderQuoteView(APIView):
    """
    POST /api/v1/orders/quote/
    คำนวณราคายอดรวมสั่งซื้อและค่าจัดส่งล่วงหน้าบน Backend (Server-Side Price Calculation)
    """
    permission_classes = [AllowAny]
    throttle_scope = 'quote'

    def post(self, request):
        serializer = OrderQuoteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        try:
            quote = calculate_order_quote(
                merchant_id=str(serializer.validated_data['merchant_id']),
                delivery_lat=serializer.validated_data['delivery_lat'],
                delivery_lng=serializer.validated_data['delivery_lng'],
                items_data=serializer.validated_data['items']
            )

            # แปลงรายการสินค้าสำหรับ Response
            items_response = [{
                'menu_item_id': str(item['menu_item'].id),
                'item_name': item['item_name'],
                'unit_price': item['unit_price'],
                'quantity': item['quantity'],
                'total_price': item['total_price'],
                'selected_options': item['selected_options']
            } for item in quote['items']]

            return Response({
                'success': True,
                'data': {
                    'merchant_id': quote['merchant_id'],
                    'merchant_name': quote['merchant_name'],
                    'subtotal': quote['subtotal'],
                    'delivery_fee': quote['delivery_fee'],
                    'total_amount': quote['total_amount'],
                    'delivery_distance_km': quote['delivery_distance_km'],
                    'items': items_response
                },
                'message': 'คำนวณราคาสั่งซื้อและค่าจัดส่งสำเร็จ'
            }, status=status.HTTP_200_OK)

        except OrderCalculationError as e:
            return Response({
                'success': False,
                'error_code': 'ORDER_QUOTE_FAILED',
                'message': str(e),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)


class PaymentQRView(APIView):
    permission_classes = [HasCustomerProfile]

    def get(self, request):
        try:
            qr_data_url, account = create_promptpay_qr(request.query_params.get('amount'))
        except ValueError as error:
            return Response({'success': False, 'error_code': 'PAYMENT_QR_FAILED', 'message': str(error), 'details': []}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'success': True, 'data': {'qr_data_url': qr_data_url, 'promptpay_account': account}})


class CreateOrderView(APIView):
    """
    POST /api/v1/orders/
    สร้างคำสั่งซื้อใหม่ (สถานะ PENDING_PAYMENT) พร้อม Snapshot ข้อมูลรายการสินค้าใน Transaction
    """
    permission_classes = [HasCustomerProfile]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            quote = calculate_order_quote(
                merchant_id=str(serializer.validated_data['merchant_id']),
                delivery_lat=serializer.validated_data['delivery_lat'],
                delivery_lng=serializer.validated_data['delivery_lng'],
                items_data=serializer.validated_data['items']
            )

            order = create_order_transaction(
                customer=request.user,
                quote_data=quote,
                delivery_address=serializer.validated_data['delivery_address'],
                note_to_merchant=serializer.validated_data.get('note_to_merchant')
            )

            order_serializer = OrderDetailSerializer(order)

            return Response({
                'success': True,
                'data': order_serializer.data,
                'message': 'สร้างคำสั่งซื้อสำเร็จ กรุณาชำระเงินและอัปโหลดสลิป'
            }, status=status.HTTP_201_CREATED)

        except OrderCalculationError as e:
            return Response({
                'success': False,
                'error_code': 'ORDER_CREATION_FAILED',
                'message': str(e),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)


class UploadSlipView(APIView):
    """
    POST /api/v1/orders/:id/upload-slip/
    อัปโหลดสลิปการโอนเงิน
    - โหมด MANUAL (default): บันทึกสลิปเป็น PENDING และรอแอดมินตรวจ (ไม่เปลี่ยนสถานะออเดอร์)
    - โหมด API/HYBRID: ตรวจอัตโนมัติ หากผ่านจึงเปลี่ยนออเดอร์เป็น PAID
    """
    permission_classes = [HasCustomerProfile]
    throttle_scope = 'slip'

    def post(self, request, order_id):
        serializer = UploadSlipSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'SLIP_INVALID_FILE',
                'message': 'กรุณาแนบรูปภาพสลิปที่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        order = Order.objects.filter(id=order_id, customer=request.user).first()
        if not order:
            return Response({
                'success': False,
                'error_code': 'ORDER_NOT_FOUND',
                'message': 'ไม่พบออเดอร์ หรือคุณไม่มีสิทธิ์เข้าถึงออเดอร์นี้',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        if order.status != OrderStatus.PENDING_PAYMENT:
            return Response({
                'success': False,
                'error_code': 'ORDER_ALREADY_PAID',
                'message': 'ออเดอร์นี้ไม่ได้อยู่ในสถานะรอชำระเงิน (อาจได้รับการยืนยันการชำระเงินแล้ว)',
                'details': []
            }, status=status.HTTP_409_CONFLICT)

        slip_image = serializer.validated_data['slip_image']
        safe_name = get_valid_filename(slip_image.name)
        storage_name = f"payment-slips/{order.id}/{uuid4().hex}_{safe_name}"
        # เก็บนอก MEDIA_ROOT และบันทึกเป็น relative name เท่านั้น (P0-05/P0-11)
        saved_name = slip_storage.save(storage_name, slip_image)
        slip_url = saved_name

        try:
            slip_image.seek(0)
            slip_tx = verify_and_process_order_slip(order, slip_image, slip_url)
        except SlipReviewError as error:
            slip_storage.delete(saved_name)
            http_status = (
                status.HTTP_429_TOO_MANY_REQUESTS
                if error.code == 'SLIP_ATTEMPTS_EXCEEDED'
                else status.HTTP_409_CONFLICT
            )
            return Response({
                'success': False,
                'error_code': error.code,
                'message': str(error),
                'details': []
            }, status=http_status)
        except SlipVerificationError as error:
            slip_storage.delete(saved_name)
            return Response({
                'success': False,
                'error_code': 'SLIP_VERIFICATION_FAILED',
                'message': str(error),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            slip_storage.delete(saved_name)
            raise

        order.refresh_from_db(fields=['status', 'paid_at'])
        review_sla = getattr(settings, 'SLIP_REVIEW_SLA_MINUTES', 15)

        if slip_tx.status == SlipStatus.APPROVED:
            message = 'ตรวจสอบสลิปสำเร็จ ยืนยันการชำระเงินเรียบร้อยแล้ว'
        else:
            message = f'อัปโหลดสลิปสำเร็จ กรุณารอแอดมินตรวจสอบ (ปกติภายใน {review_sla} นาที)'

        return Response({
            'success': True,
            'data': {
                'order_id': str(order.id),
                'order_number': order.order_number,
                'order_status': order.status,
                'slip_id': str(slip_tx.id),
                'slip_status': slip_tx.status,
                'attempt_no': slip_tx.attempt_no,
                'review_sla_minutes': review_sla,
            },
            'message': message
        }, status=status.HTTP_200_OK)


class OrderDetailView(APIView):
    """
    GET /api/v1/orders/:id/
    ดึงรายละเอียดของออเดอร์
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = Order.objects.filter(id=order_id).first()
        if not order:
            return Response({
                'success': False,
                'error_code': 'ORDER_NOT_FOUND',
                'message': 'ไม่พบคำสั่งซื้อที่ระบุ',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        can_access_order = (
            order.customer_id == request.user.id
            or order.rider_id == request.user.id
            or (hasattr(request.user, 'merchant_profile') and order.merchant_id == request.user.merchant_profile.id)
        )
        if not can_access_order:
            return Response({
                'success': False,
                'error_code': 'ORDER_ACCESS_DENIED',
                'message': 'คุณไม่มีสิทธิ์เข้าถึงออเดอร์นี้',
                'details': []
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = OrderDetailSerializer(order)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'ดึงรายละเอียดออเดอร์สำเร็จ'
        }, status=status.HTTP_200_OK)


def _parse_list_filters(request):
    """
    อ่าน query param ที่ใช้ร่วมกันของรายการออเดอร์ (P0-04)

    คืน `(filters, error_response)` — `filters` มี key `status`/`since` เฉพาะที่ส่งมา
    """
    filters = {}

    raw_status = (request.query_params.get('status') or '').strip()
    if raw_status:
        if raw_status not in OrderStatus.values:
            return None, Response({
                'success': False,
                'error_code': 'INVALID_QUERY_PARAM',
                'message': f'status ไม่ถูกต้อง: {raw_status}',
                'details': [{'field': 'status', 'allowed': list(OrderStatus.values)}],
            }, status=status.HTTP_400_BAD_REQUEST)
        filters['status'] = raw_status

    raw_since = (request.query_params.get('since') or '').strip()
    if raw_since:
        since = parse_datetime(raw_since)
        if since is None:
            return None, Response({
                'success': False,
                'error_code': 'INVALID_QUERY_PARAM',
                'message': 'since ต้องเป็นรูปแบบ ISO-8601 เช่น 2026-01-31T10:00:00Z',
                'details': [{'field': 'since'}],
            }, status=status.HTTP_400_BAD_REQUEST)
        if timezone.is_naive(since):
            since = timezone.make_aware(since, timezone.get_current_timezone())
        filters['since'] = since

    return filters, None


def _apply_list_filters(queryset, filters):
    if 'status' in filters:
        queryset = queryset.filter(status=filters['status'])
    if 'since' in filters:
        # ใช้ >= เพื่อไม่พลาดรายการที่อัปเดตพอดีกับ timestamp ที่ client ส่งมา (client dedupe เอง)
        queryset = queryset.filter(updated_at__gte=filters['since'])
    return queryset


class MerchantOrderListView(APIView):
    """
    GET /api/v1/orders/merchant-orders/?status=&since=
    ดึงรายการออเดอร์ของร้านค้า (เรียงลำดับตามเวลาสร้างล่าสุด)
    """

    permission_classes = [HasMerchantProfile]

    def get(self, request):
        filters, error = _parse_list_filters(request)
        if error:
            return error

        # ห้ามร้านเห็นออเดอร์ที่ยังไม่ชำระเงิน (กันการเตรียมอาหารก่อนได้เงิน — P0-04)
        orders_qs = _apply_list_filters(
            Order.objects.filter(merchant=request.user.merchant_profile).exclude(
                status=OrderStatus.PENDING_PAYMENT
            ),
            filters,
        )
        orders = list(
            orders_qs.select_related('merchant', 'rider', 'customer').prefetch_related(
                'items', 'slip_transactions'
            ).order_by('-created_at')[:200]
        )

        serializer = OrderDetailSerializer(orders, many=True, context={'request': request})
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'ดึงรายการออเดอร์ {len(orders)} รายการสำเร็จ'
        }, status=status.HTTP_200_OK)


class CustomerOrderListView(APIView):
    """GET /api/v1/orders/my-orders/?status=&since= คืนออเดอร์จริงของผู้ใช้ที่เข้าสู่ระบบ"""

    permission_classes = [HasCustomerProfile]

    def get(self, request):
        filters, error = _parse_list_filters(request)
        if error:
            return error

        orders = list(
            _apply_list_filters(Order.objects.filter(customer=request.user), filters)
            .select_related('merchant', 'rider')
            .prefetch_related('items', 'slip_transactions')
            .order_by('-created_at')
        )
        serializer = OrderDetailSerializer(orders, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'ดึงรายการออเดอร์ {len(orders)} รายการสำเร็จ',
        })


class OrderStatusUpdateView(APIView):
    """
    PATCH /api/v1/orders/<uuid:order_id>/status/
    อัปเดตสถานะออเดอร์ (PAID -> PREPARING -> READY_FOR_PICKUP -> COMPLETED)
    และส่ง FCM แจ้งเตือนลูกค้าแบบเรียลไทม์
    """
    permission_classes = [HasMerchantProfile]

    def patch(self, request, order_id):
        new_status = request.data.get('status')
        if not new_status:
            return Response({
                'success': False,
                'error_code': 'MISSING_STATUS',
                'message': 'กรุณาระบุสถานะใหม่ status',
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)

        order = Order.objects.filter(
            id=order_id,
            merchant=request.user.merchant_profile
        ).first()
        if not order:
            return Response({
                'success': False,
                'error_code': 'ORDER_NOT_FOUND',
                'message': 'ไม่พบออเดอร์ที่ระบุ',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        allowed_transitions = MERCHANT_ALLOWED_TRANSITIONS
        if new_status not in allowed_transitions.get(order.status, set()):
            return Response({
                'success': False,
                'error_code': 'INVALID_STATUS_TRANSITION',
                'message': f'ไม่สามารถเปลี่ยนสถานะจาก {order.status} เป็น {new_status}',
                'details': [],
            }, status=status.HTTP_409_CONFLICT)

        note = request.data.get('note') or request.data.get('reason')
        try:
            order = transition_order(
                order, new_status, actor=request.user, role='MERCHANT', note=note
            )
        except InvalidTransition as error:
            return Response({
                'success': False,
                'error_code': 'INVALID_STATUS_TRANSITION',
                'message': str(error),
                'details': [],
            }, status=status.HTTP_409_CONFLICT)

        if order.customer:
            order_id = str(order.id)
            order_number = order.order_number
            transaction.on_commit(lambda: create_and_send_notification(
                user=order.customer,
                title='อัปเดตสถานะออเดอร์',
                body=f'ออเดอร์ {order_number}: {new_status}',
                data={'type': 'ORDER_STATUS', 'order_id': order_id, 'status': new_status},
            ))

        serializer = OrderDetailSerializer(order, context={'request': request})
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'อัปเดตสถานะออเดอร์เป็น {new_status} เรียบร้อยแล้ว'
        }, status=status.HTTP_200_OK)
