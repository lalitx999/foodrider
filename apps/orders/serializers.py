from rest_framework import serializers
from apps.orders.models import Order, OrderItem


class OrderItemRequestSerializer(serializers.Serializer):
    menu_item_id = serializers.UUIDField(required=True)
    quantity = serializers.IntegerField(min_value=1, required=True)
    option_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )


class OrderQuoteRequestSerializer(serializers.Serializer):
    merchant_id = serializers.UUIDField(required=True)
    delivery_lat = serializers.FloatField(required=True)
    delivery_lng = serializers.FloatField(required=True)
    items = OrderItemRequestSerializer(many=True, required=True)


class CreateOrderSerializer(serializers.Serializer):
    merchant_id = serializers.UUIDField(required=True)
    delivery_lat = serializers.FloatField(required=True)
    delivery_lng = serializers.FloatField(required=True)
    delivery_address = serializers.CharField(required=True)
    note_to_merchant = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    items = OrderItemRequestSerializer(many=True, required=True)


class UploadSlipSerializer(serializers.Serializer):
    slip_image = serializers.FileField(
        required=True,
        error_messages={'required': 'กรุณาแนบไฟล์รูปภาพสลิปการโอนเงิน'}
    )


class OrderItemDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'item_name', 'unit_price', 'quantity', 'total_price', 'selected_options']


class OrderDetailSerializer(serializers.ModelSerializer):
    items = OrderItemDetailSerializer(many=True, read_only=True)
    merchant_name = serializers.CharField(source='merchant.name', read_only=True)
    customer_name = serializers.CharField(source='customer.display_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True, default=None)
    rider_name = serializers.CharField(source='rider.display_name', read_only=True, default=None)
    rider_phone = serializers.CharField(source='rider.phone_number', read_only=True, default=None)
    rider_vehicle_plate = serializers.CharField(source='rider.rider_profile.vehicle_plate', read_only=True, default=None)
    slip_url = serializers.SerializerMethodField()

    def get_slip_url(self, obj):
        latest_slip = obj.slip_transactions.filter(is_verified=True).order_by('-verified_at').first()
        if not latest_slip:
            latest_slip = obj.slip_transactions.order_by('-verified_at').first()
        if latest_slip and latest_slip.slip_image_url:
            url = latest_slip.slip_image_url
            if url.startswith(('http://', 'https://')):
                return url
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(url)
            from django.conf import settings
            base_url = getattr(settings, 'BACKEND_URL', 'https://foodrider.tanchonhomserverxxx.online').rstrip('/')
            if not url.startswith('/'):
                url = '/' + url
            return f"{base_url}{url}"
        return None

    class Meta:
        model = Order
        fields = [
            'id',
            'order_number',
            'status',
            'merchant_id',
            'merchant_name',
            'customer_id',
            'customer_name',
            'customer_phone',
            'rider_id',
            'rider_name',
            'rider_phone',
            'rider_vehicle_plate',
            'subtotal',
            'delivery_fee',
            'total_amount',
            'delivery_address',
            'delivery_latitude',
            'delivery_longitude',
            'delivery_distance_km',
            'note_to_merchant',
            'slip_url',
            'items',
            'created_at',
            'updated_at'
        ]
