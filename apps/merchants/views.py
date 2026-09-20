from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from apps.merchants.models import Merchant, MenuItem, Category, MenuOption
from apps.merchants.serializers import (
    MerchantListSerializer,
    CategoryWithMenuSerializer,
    StoreStatusToggleSerializer,
    MenuItemToggleSerializer,
    CreateMenuItemSerializer,
    MenuItemSerializer
)
from apps.merchants.services import get_nearby_open_merchants, get_merchant_full_menu


class MerchantListView(APIView):
    """
    GET /api/v1/merchants/?lat=xxx&lng=xxx
    ดึงรายการร้านค้าที่เปิดอยู่ เรียงลำดับตามระยะทางที่ใกล้ที่สุดผ่าน PostGIS
    """
    permission_classes = [AllowAny]

    def get(self, request):
        lat_str = request.query_params.get('lat')
        lng_str = request.query_params.get('lng')

        if not lat_str or not lng_str:
            return Response({
                'success': False,
                'error_code': 'MISSING_LAT_LNG',
                'message': 'กรุณาระบุพิกัด lat และ lng สำหรับคำนวณระยะทาง',
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            lat = float(lat_str)
            lng = float(lng_str)
            if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                raise ValueError("พิกัดละติจูด/ลองจิจูดไม่อยู่ในขอบเขตที่ถูกต้อง")
        except ValueError as e:
            return Response({
                'success': False,
                'error_code': 'INVALID_COORDINATES',
                'message': str(e),
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)

        merchants = get_nearby_open_merchants(lat, lng)
        serializer = MerchantListSerializer(merchants, many=True)

        return Response({
            'success': True,
            'data': serializer.data,
            'message': f'ดึงรายการร้านค้าที่เปิดบริการ {len(merchants)} ร้านสำเร็จ'
        }, status=status.HTTP_200_OK)


class MerchantMenuView(APIView):
    """
    GET /api/v1/merchants/:id/menu/
    ดึงโครงสร้างหมวดหมู่ และรายการอาหารของร้านค้าที่ระบุ
    """
    permission_classes = [AllowAny]

    def get(self, request, merchant_id):
        merchant = Merchant.objects.filter(id=merchant_id).first()
        if not merchant:
            return Response({
                'success': False,
                'error_code': 'MERCHANT_NOT_FOUND',
                'message': 'ไม่พบร้านค้าที่ระบุ',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        categories = get_merchant_full_menu(merchant_id)
        serializer = CategoryWithMenuSerializer(categories, many=True)

        return Response({
            'success': True,
            'data': {
                'merchant_id': str(merchant.id),
                'merchant_name': merchant.name,
                'is_open': merchant.is_open,
                'categories': serializer.data
            },
            'message': 'ดึงข้อมูลเมนูอาหารสำเร็จ'
        }, status=status.HTTP_200_OK)


class StoreStatusToggleView(APIView):
    """
    PATCH /api/v1/merchant/store-status/
    สลับสถานะเปิด/ปิดรับออเดอร์ของร้านค้า (is_open: true/false)
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = StoreStatusToggleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        merchant = Merchant.objects.filter(user=request.user).first()
        if not merchant:
            return Response({
                'success': False,
                'error_code': 'MERCHANT_PROFILE_NOT_FOUND',
                'message': 'ไม่พบโปรไฟล์ร้านค้าสำหรับผู้ใช้นี้',
                'details': []
            }, status=status.HTTP_403_FORBIDDEN)

        merchant.is_open = serializer.validated_data['is_open']
        merchant.save()

        return Response({
            'success': True,
            'data': {
                'merchant_id': str(merchant.id),
                'is_open': merchant.is_open
            },
            'message': f"เปลี่ยนสถานะร้านเป็น {'เปิดรับออเดอร์' if merchant.is_open else 'ปิดร้าน'} สำเร็จ"
        }, status=status.HTTP_200_OK)


class MenuItemToggleView(APIView):
    """
    PATCH /api/v1/merchant/menu/:id/toggle/
    สลับสถานะสินค้าหมด/มีจำหน่าย (is_available: true/false)
    """
    permission_classes = [IsAuthenticated]

    def patch(self, request, item_id):
        serializer = MenuItemToggleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        merchant = Merchant.objects.filter(user=request.user).first()
        if not merchant:
            return Response({
                'success': False,
                'error_code': 'MERCHANT_PROFILE_NOT_FOUND',
                'message': 'ไม่พบโปรไฟล์ร้านค้า',
                'details': []
            }, status=status.HTTP_403_FORBIDDEN)

        menu_item = MenuItem.objects.filter(id=item_id, merchant=merchant).first()
        if not menu_item:
            return Response({
                'success': False,
                'error_code': 'MENU_ITEM_NOT_FOUND',
                'message': 'ไม่พบรายการอาหาร หรือคุณไม่มีสิทธิ์แก้ไขเมนูนี้',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        menu_item.is_available = serializer.validated_data['is_available']
        menu_item.save()

        return Response({
            'success': True,
            'data': {
                'item_id': str(menu_item.id),
                'item_name': menu_item.name,
                'is_available': menu_item.is_available
            },
            'message': f"ปรับสถานะ {menu_item.name} เป็น {'พร้อมขาย' if menu_item.is_available else 'สินค้าหมด'} สำเร็จ"
        }, status=status.HTTP_200_OK)
