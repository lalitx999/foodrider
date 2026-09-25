from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.files.storage import default_storage
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
    OrderCalculationError
)
from apps.payments.services import verify_and_process_order_slip, SlipVerificationError
from apps.users.permissions import HasMerchantProfile, HasCustomerProfile
from apps.notifications.fcm import create_and_send_notification
from apps.payments.promptpay import create_promptpay_qr


class OrderQuoteView(APIView):
    """
    POST /api/v1/orders/quote/
    คำนวณราคายอดรวมสั่งซื้อและค่าจัดส่งล่วงหน้าบน Backend (Server-Side Price Calculation)
    """
    permission_classes = [AllowAny]

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
    รับไฟล์รูปภาพสลิปการโอนเงิน -> ยิงตรวจ Anti-Fraud -> สลับสถานะออเดอร์เป็น PAID
    """
    permission_classes = [HasCustomerProfile]

    def post(self, request, order_id):
        serializer = UploadSlipSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
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

        slip_image = serializer.validated_data['slip_image']
        safe_name = get_valid_filename(slip_image.name)
        storage_name = f"payment-slips/{order.id}/{uuid4().hex}_{safe_name}"
        saved_name = default_storage.save(storage_name, slip_image)
        slip_url = request.build_absolute_uri(default_storage.url(saved_name))

        try:
            slip_image.seek(0)
            slip_tx = verify_and_process_order_slip(order, slip_image, slip_url)
            order.refresh_from_db(fields=['status'])
            create_and_send_notification(
                user=order.merchant.user,
                title='มีออเดอร์ใหม่',
                body=f'ออเดอร์ {order.order_number} ชำระเงินและตรวจสอบสลิปแล้ว',
                data={'type': 'NEW_PAID_ORDER', 'order_id': str(order.id)},
            )
            
            return Response({
                'success': True,
                'data': {
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'status': order.status,
                    'trans_ref': slip_tx.trans_ref,
                    'amount_verified': slip_tx.amount
                },
                'message': 'ตรวจสอบสลิปสำเร็จ ยืนยันการชำระเงินเรียบร้อยแล้ว'
            }, status=status.HTTP_200_OK)

        except SlipVerificationError as e:
            default_storage.delete(saved_name)
            return Response({
                'success': False,
                'error_code': 'SLIP_VERIFICATION_FAILED',
                'message': str(e),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            default_storage.delete(saved_name)
            raise


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


class MerchantOrderListView(APIView):
    """
    GET /api/v1/orders/merchant-orders/
    ดึงรายการออเดอร์ของร้านค้า (เรียงลำดับตามเวลาสร้างล่าสุด)
    """
    permission_classes = [HasMerchantProfile]

    def get(self, request):
        orders = Order.objects.filter(
            merchant=request.user.merchant_profile
        ).order_by('-created_at')

        serializer = OrderDetailSerializer(orders, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'ดึงรายการออเดอร์ {len(orders)} รายการสำเร็จ'
        }, status=status.HTTP_200_OK)


class CustomerOrderListView(APIView):
    """GET /api/v1/orders/my-orders/ คืนออเดอร์จริงของผู้ใช้ที่เข้าสู่ระบบ"""
    permission_classes = [HasCustomerProfile]

    def get(self, request):
        orders = Order.objects.filter(customer=request.user).select_related(
            'merchant', 'rider'
        ).prefetch_related('items').order_by('-created_at')
        serializer = OrderDetailSerializer(orders, many=True)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'ดึงรายการออเดอร์ {orders.count()} รายการสำเร็จ',
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

        allowed_transitions = {
            OrderStatus.PAID: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
            OrderStatus.PREPARING: {OrderStatus.READY_FOR_PICKUP, OrderStatus.CANCELLED},
        }
        if new_status not in allowed_transitions.get(order.status, set()):
            return Response({
                'success': False,
                'error_code': 'INVALID_STATUS_TRANSITION',
                'message': f'ไม่สามารถเปลี่ยนสถานะจาก {order.status} เป็น {new_status}',
                'details': [],
            }, status=status.HTTP_409_CONFLICT)

        order.status = new_status
        order.save(update_fields=['status', 'updated_at'])

        if order.customer:
            create_and_send_notification(
                user=order.customer,
                title='อัปเดตสถานะออเดอร์',
                body=f'ออเดอร์ {order.order_number}: {new_status}',
                data={'type': 'ORDER_STATUS', 'order_id': str(order.id), 'status': new_status},
            )

        serializer = OrderDetailSerializer(order)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'อัปเดตสถานะออเดอร์เป็น {new_status} เรียบร้อยแล้ว'
        }, status=status.HTTP_200_OK)
