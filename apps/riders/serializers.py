from rest_framework import serializers
from apps.riders.models import RiderProfile
from apps.orders.models import Order


class RiderStatusToggleSerializer(serializers.Serializer):
    is_online = serializers.BooleanField(required=True)
    current_lat = serializers.FloatField(required=False, allow_null=True)
    current_lng = serializers.FloatField(required=False, allow_null=True)

    def validate(self, attrs):
        lat, lng = attrs.get('current_lat'), attrs.get('current_lng')
        if (lat is None) != (lng is None):
            raise serializers.ValidationError('ต้องส่งละติจูดและลองจิจูดพร้อมกัน')
        if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise serializers.ValidationError('พิกัดอยู่นอกขอบเขตที่ถูกต้อง')
        return attrs


class CompleteOrderSerializer(serializers.Serializer):
    proof_image = serializers.ImageField(required=True)
    signature_image = serializers.ImageField(required=True)
    recipient_confirmed = serializers.BooleanField(required=True)

    def validate_recipient_confirmed(self, value):
        if not value:
            raise serializers.ValidationError('ต้องยืนยันผู้รับก่อนปิดงาน')
        return value


class AvailableJobSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_address = serializers.CharField(source='merchant.address', read_only=True)
    merchant_lat = serializers.DecimalField(source='merchant.latitude', max_digits=10, decimal_places=7, read_only=True)
    merchant_lng = serializers.DecimalField(source='merchant.longitude', max_digits=10, decimal_places=7, read_only=True)
    google_maps_url = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source='customer.display_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    merchant_phone = serializers.CharField(source='merchant.phone_number', read_only=True)
    items = serializers.SerializerMethodField()


    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'status',
            'merchant_name',
            'merchant_address',
            'merchant_lat',
            'merchant_lng',
            'delivery_address',
            'delivery_latitude',
            'delivery_longitude',
            'delivery_distance_km',
            'rider_delivery_fee',
            'google_maps_url',
            'customer_name',
            'customer_phone',
            'merchant_phone',
            'items',
            'created_at'
        ]

    def get_google_maps_url(self, obj):
        # สร้าง Google Maps Deep Link แบบมาตรฐาน (ไม่ต้องเสียค่า API Key)
        return f"https://www.google.com/maps/dir/?api=1&destination={obj.merchant.latitude},{obj.merchant.longitude}"

    def get_items(self, obj):
        return [{'name': item.item_name, 'quantity': item.quantity, 'price': item.unit_price} for item in obj.items.all()]
