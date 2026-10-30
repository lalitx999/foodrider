import math

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from rest_framework import serializers
from apps.orders.models import Order, OrderItem
from apps.payments.models import SlipStatus

ALLOWED_SLIP_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_SLIP_FORMATS = {'JPEG', 'PNG', 'WEBP'}

# P0-06: เพดานจำนวน/ขนาดข้อมูลที่รับจากลูกค้า
MAX_ITEMS_PER_ORDER = 30
MAX_QUANTITY_PER_ITEM = 20
MAX_NOTE_LENGTH = 500
MAX_ADDRESS_LENGTH = 500


class OrderItemRequestSerializer(serializers.Serializer):
    menu_item_id = serializers.UUIDField(required=True)
    quantity = serializers.IntegerField(min_value=1, max_value=MAX_QUANTITY_PER_ITEM, required=True)
    option_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list
    )


class CoordinateValidationMixin:
    """P0-06: กัน NaN/Infinity ที่ผ่าน FloatField มาได้"""

    def validate_delivery_lat(self, value):
        if not math.isfinite(value):
            raise serializers.ValidationError('พิกัดละติจูดไม่ถูกต้อง')
        return value

    def validate_delivery_lng(self, value):
        if not math.isfinite(value):
            raise serializers.ValidationError('พิกัดลองจิจูดไม่ถูกต้อง')
        return value


class OrderQuoteRequestSerializer(CoordinateValidationMixin, serializers.Serializer):
    merchant_id = serializers.UUIDField(required=True)
    delivery_lat = serializers.FloatField(required=True, min_value=-90, max_value=90)
    delivery_lng = serializers.FloatField(required=True, min_value=-180, max_value=180)
    items = OrderItemRequestSerializer(many=True, required=True, max_length=MAX_ITEMS_PER_ORDER)


class CreateOrderSerializer(CoordinateValidationMixin, serializers.Serializer):
    merchant_id = serializers.UUIDField(required=True)
    delivery_lat = serializers.FloatField(required=True, min_value=-90, max_value=90)
    delivery_lng = serializers.FloatField(required=True, min_value=-180, max_value=180)
    delivery_address = serializers.CharField(required=True, max_length=MAX_ADDRESS_LENGTH)
    note_to_merchant = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=MAX_NOTE_LENGTH
    )
    items = OrderItemRequestSerializer(many=True, required=True, max_length=MAX_ITEMS_PER_ORDER)


class UploadSlipSerializer(serializers.Serializer):
    slip_image = serializers.FileField(
        required=True,
        error_messages={'required': 'กรุณาแนบไฟล์รูปภาพสลิปการโอนเงิน'}
    )

    def validate_slip_image(self, f):
        max_bytes = int(getattr(settings, 'SLIP_MAX_FILE_BYTES', 5 * 1024 * 1024))
        if f.size > max_bytes:
            raise serializers.ValidationError('ไฟล์สลิปต้องมีขนาดไม่เกิน 5MB')
        if getattr(f, 'content_type', '') not in ALLOWED_SLIP_CONTENT_TYPES:
            raise serializers.ValidationError('รองรับเฉพาะไฟล์รูปภาพ JPG, PNG หรือ WEBP')

        # ตรวจ magic bytes — กันไฟล์ที่ปลอม content_type มา
        try:
            f.seek(0)
            with Image.open(f) as image:
                image_format = image.format
                image.verify()
            f.seek(0)
        except (UnidentifiedImageError, OSError, ValueError):
            raise serializers.ValidationError('ไฟล์ที่อัปโหลดไม่ใช่รูปภาพที่ถูกต้อง')

        if image_format not in ALLOWED_SLIP_FORMATS:
            raise serializers.ValidationError('รองรับเฉพาะไฟล์รูปภาพ JPG, PNG หรือ WEBP')
        return f


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
    slip_status = serializers.SerializerMethodField()
    slip_reject_reason = serializers.SerializerMethodField()
    slip_attempt_no = serializers.SerializerMethodField()
    slip_uploaded_at = serializers.SerializerMethodField()
    paid_at = serializers.DateTimeField(read_only=True)

    def _slips(self, obj):
        """cache รายการสลิปไว้ใช้หลาย field (กัน N+1 ซ้ำซ้อนในแถวเดียวกัน)"""
        if not hasattr(obj, '_slips_cache'):
            obj._slips_cache = list(obj.slip_transactions.all())
        return obj._slips_cache

    def _current_slip(self, obj):
        slips = self._slips(obj)
        if not slips:
            return None
        approved = next((s for s in slips if s.status == SlipStatus.APPROVED), None)
        return approved or slips[0]

    def get_slip_status(self, obj):
        slip = self._current_slip(obj)
        return slip.status if slip else None

    def get_slip_reject_reason(self, obj):
        slip = self._current_slip(obj)
        return slip.reject_reason if slip else None

    def get_slip_attempt_no(self, obj):
        slip = self._current_slip(obj)
        return slip.attempt_no if slip else 0

    def get_slip_uploaded_at(self, obj):
        slip = self._current_slip(obj)
        return slip.created_at if slip else None

    def get_slip_url(self, obj):
        """คืน signed URL อายุ 10 นาที (ห้ามคืน /media/... ตรง ๆ — P0-05)"""
        latest_slip = self._current_slip(obj)
        if not latest_slip or not latest_slip.slip_image_url:
            return None

        from django.urls import reverse
        from apps.users.media_tokens import make_media_token

        token = make_media_token(latest_slip.id)
        path = reverse('media-slip', kwargs={'slip_id': latest_slip.id, 'token': token})
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(path)
        base_url = getattr(settings, 'BACKEND_URL', 'https://foodrider.tanchonhomserverxxx.online').rstrip('/')
        return f"{base_url}{path}"

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
            'slip_status',
            'slip_reject_reason',
            'slip_attempt_no',
            'slip_uploaded_at',
            'paid_at',
            'items',
            'created_at',
            'updated_at'
        ]
