from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
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


class CreateOrderView(APIView):
    """
    POST /api/v1/orders/
    สร้างคำสั่งซื้อใหม่ (สถานะ PENDING_PAYMENT) พร้อม Snapshot ข้อมูลรายการสินค้าใน Transaction
    """
    permission_classes = [IsAuthenticated]

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
    permission_classes = [IsAuthenticated]

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
        slip_url = f"https://storage.yourdomain.com/slips/{order.id}_{slip_image.name}"

        try:
            slip_tx = verify_and_process_order_slip(order, slip_image, slip_url)
            
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
            return Response({
                'success': False,
                'error_code': 'SLIP_VERIFICATION_FAILED',
                'message': str(e),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)


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

        serializer = OrderDetailSerializer(order)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'ดึงรายละเอียดออเดอร์สำเร็จ'
        }, status=status.HTTP_200_OK)
