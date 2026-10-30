from rest_framework import serializers
from apps.riders.models import RiderProfile
from apps.riders.navigation import (
    build_navigation_target,
    build_order_navigation,
    estimate_delivery_minutes,
    normalize_coordinate_pair,
    to_coordinate,
)
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
    merchant_lat = serializers.SerializerMethodField()
    merchant_lng = serializers.SerializerMethodField()
    delivery_latitude = serializers.SerializerMethodField()
    delivery_longitude = serializers.SerializerMethodField()
    google_maps_url = serializers.SerializerMethodField()
    navigation = serializers.SerializerMethodField()
    estimated_time = serializers.SerializerMethodField()
    rider_earning = serializers.SerializerMethodField()
    cod_amount = serializers.SerializerMethodField()
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
            'rider_earning',
            'cod_amount',
            'estimated_time',
            'navigation',
            'google_maps_url',
            'customer_name',
            'customer_phone',
            'merchant_phone',
            'items',
            'created_at'
        ]

    def _merchant_coordinates(self, obj):
        return normalize_coordinate_pair(obj.merchant.latitude, obj.merchant.longitude)

    def _delivery_coordinates(self, obj):
        return normalize_coordinate_pair(obj.delivery_latitude, obj.delivery_longitude)

    def get_merchant_lat(self, obj):
        coordinates = self._merchant_coordinates(obj)
        return coordinates[0] if coordinates else None

    def get_merchant_lng(self, obj):
        coordinates = self._merchant_coordinates(obj)
        return coordinates[1] if coordinates else None

    def get_delivery_latitude(self, obj):
        coordinates = self._delivery_coordinates(obj)
        return coordinates[0] if coordinates else None

    def get_delivery_longitude(self, obj):
        coordinates = self._delivery_coordinates(obj)
        return coordinates[1] if coordinates else None

    def get_google_maps_url(self, obj):
        # destination = จุดส่งของลูกค้า (ไม่ใช่ร้าน) และคืน None ถ้าพิกัดไม่ครบ
        coordinates = self._delivery_coordinates(obj)
        if coordinates is None:
            return None
        return build_navigation_target(coordinates[0], coordinates[1])['google_maps_url']

    def get_navigation(self, obj):
        origin = self.context.get('origin') or (None, None)
        return build_order_navigation(obj, origin[0], origin[1])

    def get_estimated_time(self, obj):
        minutes = estimate_delivery_minutes(obj.delivery_distance_km)
        return f'{minutes} นาที' if minutes is not None else None

    def get_rider_earning(self, obj):
        return to_coordinate(obj.rider_delivery_fee)

    def get_cod_amount(self, obj):
        # ยอดที่ไรเดอร์ต้องเก็บจากลูกค้าปลายทาง (ยอดรวมออเดอร์)
        return to_coordinate(obj.total_amount)

    def get_items(self, obj):
        return [{'name': item.item_name, 'quantity': item.quantity, 'price': item.unit_price} for item in obj.items.all()]


class RiderActiveJobSerializer(AvailableJobSerializer):
    """
    GET /api/v1/rider/orders/active/ — งานที่ไรเดอร์คนนี้กำลังจัดส่งอยู่
    ใช้รูปแบบข้อมูลเดียวกับงานว่าง แต่ navigation ใส่ origin จากพิกัดไรเดอร์ล่าสุดได้
    """

    merchant = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()

    class Meta(AvailableJobSerializer.Meta):
        fields = AvailableJobSerializer.Meta.fields + ['merchant', 'customer']

    def _merchant_coordinates(self, obj):
        return normalize_coordinate_pair(obj.merchant.latitude, obj.merchant.longitude)

    def get_merchant(self, obj):
        merchant = obj.merchant
        coordinates = self._merchant_coordinates(obj)
        return {
            'id': str(merchant.id),
            'name': merchant.name,
            'phone_number': merchant.phone_number,
            'address': merchant.address,
            'latitude': coordinates[0] if coordinates else None,
            'longitude': coordinates[1] if coordinates else None,
        }

    def get_customer(self, obj):
        coordinates = self._delivery_coordinates(obj)
        customer = obj.customer
        return {
            'display_name': customer.display_name,
            'phone_number': customer.phone_number,
            'delivery_address': obj.delivery_address,
            'delivery_latitude': coordinates[0] if coordinates else None,
            'delivery_longitude': coordinates[1] if coordinates else None,
        }
