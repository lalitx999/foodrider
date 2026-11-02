import re

from rest_framework import serializers
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption
from apps.merchants.validators import validate_uploaded_image


class MenuOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuOption
        fields = ['id', 'name', 'extra_price']


class MenuItemSerializer(serializers.ModelSerializer):
    options = MenuOptionSerializer(many=True, read_only=True)
    image_url = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True, default='ไม่มีหมวดหมู่')

    def get_image_url(self, obj):
        url = obj.image.url if obj.image else obj.image_url
        if not url:
            return None
        if url.startswith('/'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(url)
            from django.conf import settings
            backend_base = getattr(settings, 'BACKEND_BASE_URL', 'https://foodrider.tanchonhomserverxxx.online')
            return f"{backend_base.rstrip('/')}{url}"
        return url

    class Meta:
        model = MenuItem
        fields = ['id', 'name', 'description', 'price', 'image_url', 'is_available', 'category', 'category_name', 'options']


class CategoryWithMenuSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'sort_order', 'items']

    def get_items(self, obj):
        # ดึงเฉพาะรายการอาหารที่เปิดขายอยู่ (is_available = True)
        available_items = obj.items.filter(is_available=True)
        return MenuItemSerializer(available_items, many=True, context=self.context).data


class MerchantListSerializer(serializers.ModelSerializer):
    distance_km = serializers.FloatField(read_only=True)
    image_url = serializers.SerializerMethodField()

    def get_image_url(self, obj):
        value = obj.image_url
        if not value:
            return None
        if value.startswith('/'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(value)
            from django.conf import settings
            backend_base = getattr(settings, 'BACKEND_BASE_URL', 'https://foodrider.tanchonhomserverxxx.online')
            return f"{backend_base.rstrip('/')}{value}"
        return value

    class Meta:
        model = Merchant
        fields = [
            'id',
            'name',
            'description',
            'image_url',
            'phone_number',
            'address',
            'latitude',
            'longitude',
            'is_open',
            'distance_km'
        ]


class StoreStatusToggleSerializer(serializers.Serializer):
    is_open = serializers.BooleanField(
        required=True,
        error_messages={'required': 'กรุณาระบุสวิตช์เปิด/ปิดร้าน is_open'}
    )


class MenuItemToggleSerializer(serializers.Serializer):
    is_available = serializers.BooleanField(
        required=True,
        error_messages={'required': 'กรุณาระบุสวิตช์สถานะเมนู is_available'}
    )


class CreateMenuItemSerializer(serializers.Serializer):
    category_id = serializers.UUIDField(required=False, allow_null=True)
    name = serializers.CharField(max_length=255, required=True)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    image_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    options = MenuOptionSerializer(many=True, required=False, default=list)


# ---------------- ข้อมูลร้าน + คำขอเปลี่ยนบัญชี (module_32 เฟส A) ----------------
PHONE_PATTERN = re.compile(r'^[0-9+\-\s]{9,15}$')


class MerchantProfileUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False)
    address = serializers.CharField(max_length=500, required=False)
    latitude = serializers.FloatField(required=False, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, min_value=-180, max_value=180)
    image = serializers.FileField(required=False)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('ชื่อร้านห้ามว่าง')
        return value.strip()

    def validate_address(self, value):
        if not value.strip():
            raise serializers.ValidationError('ที่อยู่ร้านห้ามว่าง')
        return value.strip()

    def validate_phone_number(self, value):
        if not PHONE_PATTERN.match(value.strip()):
            raise serializers.ValidationError('เบอร์โทรไม่ถูกต้อง')
        return value.strip()

    def validate_image(self, value):
        return validate_uploaded_image(value)

    def validate(self, attrs):
        has_lat, has_lng = 'latitude' in attrs, 'longitude' in attrs
        if has_lat != has_lng:
            raise serializers.ValidationError({'location': 'ต้องส่ง latitude และ longitude มาพร้อมกัน'})
        if has_lat and attrs['latitude'] == 0 and attrs['longitude'] == 0:
            raise serializers.ValidationError({'location': 'พิกัด 0,0 ไม่ใช่ตำแหน่งจริงของร้าน'})
        return attrs


class BankChangeRequestSerializer(serializers.Serializer):
    bank_name = serializers.CharField(max_length=100)
    bank_account_name = serializers.CharField(max_length=255)
    bank_account_number = serializers.CharField(max_length=30)

    def validate_bank_account_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('ชื่อบัญชีห้ามว่าง')
        return value.strip()

    def validate_bank_account_number(self, value):
        digits = re.sub(r'[\s\-]', '', value)
        if not digits.isdigit() or not 10 <= len(digits) <= 15:
            raise serializers.ValidationError('เลขบัญชีต้องเป็นตัวเลข 10–15 หลัก')
        return digits
