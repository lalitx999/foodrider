from rest_framework import serializers
from apps.riders.models import RiderProfile
from apps.orders.models import Order


class RiderStatusToggleSerializer(serializers.Serializer):
    is_online = serializers.BooleanField(required=True)
    current_lat = serializers.FloatField(required=False, allow_null=True)
    current_lng = serializers.FloatField(required=False, allow_null=True)


class CompleteOrderSerializer(serializers.Serializer):
    proof_image_url = serializers.CharField(required=True)


class AvailableJobSerializer(serializers.ModelSerializer):
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    merchant_address = serializers.CharField(source='merchant.address', read_only=True)
    merchant_lat = serializers.DecimalField(source='merchant.latitude', max_digits=10, decimal_places=7, read_only=True)
    merchant_lng = serializers.DecimalField(source='merchant.longitude', max_digits=10, decimal_places=7, read_only=True)
    google_maps_url = serializers.SerializerMethodField()


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
            'created_at'
        ]

    def get_google_maps_url(self, obj):
        # สร้าง Google Maps Deep Link แบบมาตรฐาน (ไม่ต้องเสียค่า API Key)
        return f"https://www.google.com/maps/dir/?api=1&destination={obj.merchant.latitude},{obj.merchant.longitude}"
