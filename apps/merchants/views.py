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


import json

class CategoryManageView(APIView):
    permission_classes = [HasMerchantProfile]

    def get(self, request):
        merchant = request.user.merchant_profile
        categories = Category.objects.filter(merchant=merchant).order_by('sort_order', 'name')
        data = [{'id': str(cat.id), 'name': cat.name, 'sort_order': cat.sort_order} for cat in categories]
        return Response({'success': True, 'data': data}, status=status.HTTP_200_OK)

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'success': False, 'message': 'กรุณาระบุชื่อหมวดหมู่'}, status=status.HTTP_400_BAD_REQUEST)
        merchant = request.user.merchant_profile
        category, created = Category.objects.get_or_create(
            merchant=merchant,
            name=name,
            defaults={'sort_order': Category.objects.filter(merchant=merchant).count()}
        )
        return Response({'success': True, 'data': {'id': str(category.id), 'name': category.name}, 'message': 'สร้างหมวดหมู่สำเร็จ'}, status=status.HTTP_201_CREATED)


class MenuItemCreateView(APIView):
    permission_classes = [HasMerchantProfile]

    @transaction.atomic
    def post(self, request):
        merchant = request.user.merchant_profile
        data = request.data.copy()

        name = data.get('name', '').strip()
        price = data.get('price')

        if not name or not price:
            return Response({'success': False, 'message': 'กรุณาระบุชื่อเมนูและราคาให้ครบถ้วน'}, status=status.HTTP_400_BAD_REQUEST)

        # Handle category
        category = None
        category_id = data.get('category_id')
        category_name = data.get('category_name')

        if category_id:
            category = Category.objects.filter(id=category_id, merchant=merchant).first()
        elif category_name:
            category, _ = Category.objects.get_or_create(
                merchant=merchant,
                name=category_name.strip(),
                defaults={'sort_order': Category.objects.filter(merchant=merchant).count()}
            )

        if not category:
            category, _ = Category.objects.get_or_create(
                merchant=merchant,
                name='เมนูทั่วไป',
                defaults={'sort_order': 0}
            )

        # Handle options (toppings)
        raw_options = data.get('options', [])
        if isinstance(raw_options, str):
            try:
                raw_options = json.loads(raw_options)
            except Exception:
                raw_options = []

        item = MenuItem.objects.create(
            merchant=merchant,
            category=category,
            name=name,
            description=data.get('description', ''),
            price=price,
            image_url=data.get('image_url', ''),
            image=request.FILES.get('image') if 'image' in request.FILES else None
        )

        for opt in raw_options:
            if isinstance(opt, dict) and opt.get('name'):
                MenuOption.objects.create(
                    menu_item=item,
                    name=opt['name'].strip(),
                    extra_price=opt.get('extra_price', 0)
                )

        return Response({
            'success': True,
            'data': MenuItemSerializer(item, context={'request': request}).data,
            'message': 'เพิ่มเมนูอาหารเรียบร้อยแล้ว'
        }, status=status.HTTP_201_CREATED)


class MenuItemDetailView(APIView):
    permission_classes = [HasMerchantProfile]

    @transaction.atomic
    def patch(self, request, item_id):
        merchant = request.user.merchant_profile
        item = MenuItem.objects.filter(id=item_id, merchant=merchant).first()
        if not item:
            return Response({'success': False, 'message': 'ไม่พบเมนูที่ระบุ'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'name' in data:
            item.name = data['name'].strip()
        if 'price' in data:
            item.price = data['price']
        if 'description' in data:
            item.description = data['description']
        if 'image_url' in data:
            item.image_url = data['image_url']
        if 'image' in request.FILES:
            item.image = request.FILES['image']
        if 'is_available' in data:
            item.is_available = str(data['is_available']).lower() in ['true', '1']

        category_id = data.get('category_id')
        category_name = data.get('category_name')
        if category_id:
            category = Category.objects.filter(id=category_id, merchant=merchant).first()
            if category:
                item.category = category
        elif category_name:
            category, _ = Category.objects.get_or_create(
                merchant=merchant,
                name=category_name.strip(),
                defaults={'sort_order': Category.objects.filter(merchant=merchant).count()}
            )
            item.category = category

        item.save()

        # Update options if provided
        if 'options' in data:
            raw_options = data['options']
            if isinstance(raw_options, str):
                try:
                    raw_options = json.loads(raw_options)
                except Exception:
                    raw_options = None

            if isinstance(raw_options, list):
                item.options.all().delete()
                for opt in raw_options:
                    if isinstance(opt, dict) and opt.get('name'):
                        MenuOption.objects.create(
                            menu_item=item,
                            name=opt['name'].strip(),
                            extra_price=opt.get('extra_price', 0)
                        )

        return Response({
            'success': True,
            'data': MenuItemSerializer(item, context={'request': request}).data,
            'message': 'อัปเดตเมนูเรียบร้อยแล้ว'
        }, status=status.HTTP_200_OK)

    def delete(self, request, item_id):
        merchant = request.user.merchant_profile
        item = MenuItem.objects.filter(id=item_id, merchant=merchant).first()
        if not item:
            return Response({'success': False, 'message': 'ไม่พบเมนูที่ระบุ'}, status=status.HTTP_404_NOT_FOUND)

        item.delete()
        return Response({'success': True, 'message': 'ลบเมนูเรียบร้อยแล้ว'}, status=status.HTTP_200_OK)
