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
from apps.users.permissions import HasMerchantProfile
from django.db import transaction


class MerchantListView(APIView):
    """
    GET /api/v1/merchants/?lat=xxx&lng=xxx
    ดึงรายการร้านค้าที่เปิดอยู่ เรียงลำดับตามระยะทางที่ใกล้ที่สุดผ่าน PostGIS
    """
    permission_classes = [AllowAny]

    def get(self, request):
        lat_str = request.query_params.get('lat', '12.9276')
        lng_str = request.query_params.get('lng', '100.8771')

        try:
            lat = float(lat_str) if lat_str else 12.9276
            lng = float(lng_str) if lng_str else 100.8771
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
        serializer = MerchantListSerializer(merchants, many=True, context={'request': request})

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
    permission_classes = [HasMerchantProfile]

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
                'message': 'ไม่พบโปรไฟล์ร้านค้าในระบบ',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

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


class MerchantDashboardView(APIView):
    permission_classes = [HasMerchantProfile]

    def get(self, request):
        merchant = request.user.merchant_profile
        menu_items = merchant.menu_items.select_related('category').order_by('category__sort_order', 'name')
        return Response({'success': True, 'data': {
            'id': str(merchant.id), 'name': merchant.name, 'is_open': merchant.is_open,
            'menu_items': [{
                'id': str(item.id), 'name': item.name,
                'category': item.category.name if item.category else 'ไม่มีหมวดหมู่',
                'price': item.price, 'is_available': item.is_available,
            } for item in menu_items],
        }})


class MenuItemToggleView(APIView):
    """
    PATCH /api/v1/merchant/menu/:id/toggle/
    สลับสถานะสินค้าหมด/มีจำหน่าย (is_available: true/false)
    """
    permission_classes = [HasMerchantProfile]

    def patch(self, request, item_id):
        serializer = MenuItemToggleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        menu_item = MenuItem.objects.filter(id=item_id).first()
        if not menu_item:
            return Response({
                'success': False,
                'error_code': 'MENU_ITEM_NOT_FOUND',
                'message': 'ไม่พบรายการอาหารที่ระบุ',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        if menu_item.merchant.user_id != request.user.id:
            return Response({
                'success': False,
                'error_code': 'MENU_ITEM_ACCESS_DENIED',
                'message': 'คุณไม่มีสิทธิ์จัดการเมนูของร้านนี้',
                'details': []
            }, status=status.HTTP_403_FORBIDDEN)

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


class MenuItemCreateView(APIView):
    permission_classes = [HasMerchantProfile]

    @transaction.atomic
    def post(self, request):
        serializer = CreateMenuItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        category = None
        if data.get('category_id'):
            category = Category.objects.filter(id=data['category_id'], merchant=request.user.merchant_profile).first()
            if not category:
                return Response({'success': False, 'error_code': 'CATEGORY_NOT_FOUND', 'message': 'ไม่พบหมวดหมู่ของร้านนี้', 'details': []}, status=status.HTTP_404_NOT_FOUND)
        else:
            category, _ = Category.objects.get_or_create(
                merchant=request.user.merchant_profile,
                name='เมนูทั่วไป',
                defaults={'sort_order': 0},
            )
        options = data.pop('options', [])
        data.pop('category_id', None)
        item = MenuItem.objects.create(merchant=request.user.merchant_profile, category=category, **data)
        MenuOption.objects.bulk_create([MenuOption(menu_item=item, **option) for option in options])
        return Response({'success': True, 'data': MenuItemSerializer(item).data, 'message': 'เพิ่มเมนูเรียบร้อยแล้ว'}, status=status.HTTP_201_CREATED)
