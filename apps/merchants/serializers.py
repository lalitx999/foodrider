from rest_framework import serializers
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


class MenuOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuOption
        fields = ['id', 'name', 'extra_price']


class MenuItemSerializer(serializers.ModelSerializer):
    options = MenuOptionSerializer(many=True, read_only=True)

    class Meta:
        model = MenuItem
        fields = ['id', 'name', 'description', 'price', 'image_url', 'is_available', 'options']


class CategoryWithMenuSerializer(serializers.ModelSerializer):
    items = serializers.SerializerMethodField()


    class Meta:
        model = Category
        fields = ['id', 'name', 'sort_order', 'items']

    def get_items(self, obj):
        # ดึงเฉพาะรายการอาหารที่เปิดขายอยู่ (is_available = True)
        available_items = obj.items.filter(is_available=True)
        return MenuItemSerializer(available_items, many=True).data


class MerchantListSerializer(serializers.ModelSerializer):
    distance_km = serializers.FloatField(read_only=True)
    image_url = serializers.SerializerMethodField()

    def get_image_url(self, obj):
        value = obj.image_url
        if not value:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(value) if request and value.startswith('/') else value

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
