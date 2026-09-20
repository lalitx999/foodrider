from django.contrib.gis.geos import Point
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from apps.orders.models import Order, OrderStatus
from apps.merchants.models import Merchant
from apps.riders.models import RiderProfile
from apps.riders.serializers import (
    RiderStatusToggleSerializer,
    AvailableJobSerializer,
    CompleteOrderSerializer
)
from apps.riders.services import claim_rider_job_atomic, complete_rider_job_atomic, JobClaimError


class RiderStatusToggleView(APIView):
    """
    PATCH /api/v1/rider/status/
    สลับสถานะพร้อมรับงาน (is_online: true/false) และอัปเดตพิกัดตำแหน่งปัจจุบัน
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = RiderStatusToggleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        profile, created = RiderProfile.objects.get_or_create(
            user=request.user,
            defaults={'vehicle_plate': 'กข-1234'}
        )

        is_online = serializer.validated_data['is_online']
        lat = serializer.validated_data.get('current_lat')
        lng = serializer.validated_data.get('current_lng')

        profile.is_online = is_online
        if lat and lng:
            profile.current_latitude = lat
            profile.current_longitude = lng
            profile.current_location = Point(lng, lat, srid=4326)

        profile.save()

        return Response({
            'success': True,
            'data': {
                'rider_id': str(profile.id),
                'is_online': profile.is_online,
                'wallet_balance': profile.wallet_balance
            },
            'message': f"สลับสถานะเป็น {'พร้อมรับงาน' if profile.is_online else 'ปิดรับงาน'} สำเร็จ"
        }, status=status.HTTP_200_OK)


class AvailableJobsListView(APIView):
    """
    GET /api/v1/rider/orders/available/
    ดึงรายการงานว่างทั้งหมดที่พร้อมให้ไรเดอร์กดรับ (status = READY_FOR_PICKUP และยังไม่มีไรเดอร์รับงาน)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        available_orders = Order.objects.filter(
            status=OrderStatus.READY_FOR_PICKUP,
            rider__isnull=True
        ).select_related('merchant').order_by('-created_at')

        serializer = AvailableJobSerializer(available_orders, many=True)

        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'ดึงรายการงานว่าง {len(available_orders)} งานสำเร็จ'
        }, status=status.HTTP_200_OK)


class ClaimJobView(APIView):
    """
    POST /api/v1/rider/orders/:id/claim/
    ไรเดอร์กดยืนยันรับงาน (ใช้ Row Locking select_for_update ป้องกันคนกดรับงานซ้ำ)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = claim_rider_job_atomic(request.user, str(order_id))
            
            # Google Maps Navigation Deep Links
            merchant_nav = f"https://www.google.com/maps/dir/?api=1&destination={order.merchant.latitude},{order.merchant.longitude}"
            customer_nav = f"https://www.google.com/maps/dir/?api=1&destination={order.delivery_latitude},{order.delivery_longitude}"

            return Response({
                'success': True,
                'data': {
                    'order_id': str(order.id),
                    'order_number': order.order_number,
                    'status': order.status,
                    'merchant_nav_url': merchant_nav,
                    'customer_nav_url': customer_nav
                },
                'message': 'กดยืนยันรับงานเดลิเวอรีสำเร็จ'
            }, status=status.HTTP_200_OK)

        except JobClaimError as e:
            return Response({
                'success': False,
                'error_code': 'JOB_ALREADY_CLAIMED',
                'message': str(e),
                'details': []
            }, status=status.HTTP_409_CONFLICT)


class CompleteJobView(APIView):
    """
    POST /api/v1/rider/orders/:id/complete/
    ไรเดอร์แนบรูปหลักฐานการส่งมอบ ปิดงาน และรับเครดิตค่ารอบเข้า Wallet
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        serializer = CompleteOrderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'กรุณาแนบรูปภาพหลักฐานการส่งมอบ',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            proof_url = serializer.validated_data['proof_image_url']
            order = complete_rider_job_atomic(request.user, str(order_id), proof_url)
            rider_profile = RiderProfile.objects.get(user=request.user)

            return Response({
                'success': True,
                'data': {
                    'order_id': str(order.id),
                    'status': order.status,
                    'rider_fee_earned': order.rider_delivery_fee,
                    'current_wallet_balance': rider_profile.wallet_balance
                },
                'message': 'ปิดงานจัดส่งสำเร็จ เพิ่มเครดิตค่าตอบแทนเข้ากระเป๋าเงินเรียบร้อยแล้ว'
            }, status=status.HTTP_200_OK)

        except JobClaimError as e:
            return Response({
                'success': False,
                'error_code': 'JOB_COMPLETION_FAILED',
                'message': str(e),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)


class MerchantOrderReadyView(APIView):
    """
    POST /api/v1/merchant/orders/:id/ready/
    ร้านค้ากดอาหารทำเสร็จแล้ว (เปลี่ยนสถานะจาก PREPARING -> READY_FOR_PICKUP) เพื่อปล่อยงานให้ไรเดอร์เห็น
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        merchant = Merchant.objects.filter(user=request.user).first()
        if not merchant:
            return Response({
                'success': False,
                'error_code': 'MERCHANT_NOT_FOUND',
                'message': 'ไม่พบร้านค้าของคุณ',
                'details': []
            }, status=status.HTTP_403_FORBIDDEN)

        order = Order.objects.filter(id=order_id, merchant=merchant).first()
        if not order:
            return Response({
                'success': False,
                'error_code': 'ORDER_NOT_FOUND',
                'message': 'ไม่พบออเดอร์ของร้านท่าน',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        order.status = OrderStatus.READY_FOR_PICKUP
        order.save()

        return Response({
            'success': True,
            'data': {
                'order_id': str(order.id),
                'order_number': order.order_number,
                'status': order.status
            },
            'message': 'ปรับสถานะเป็น READY_FOR_PICKUP ปล่อยงานให้ไรเดอร์รับเรียบร้อยแล้ว'
        }, status=status.HTTP_200_OK)
