from django.urls import reverse
from rest_framework import serializers

from apps.payments.models import SlipTransaction
from apps.users.media_tokens import make_media_token


class AdminSlipSerializer(serializers.ModelSerializer):
    """สลิปในคิว backoffice (P1-09) — คืน signed file url + ข้อมูลออเดอร์/ลูกค้า/ร้าน"""

    order = serializers.SerializerMethodField()
    customer = serializers.SerializerMethodField()
    merchant = serializers.SerializerMethodField()
    slip_file_url = serializers.SerializerMethodField()
    amount_matches = serializers.SerializerMethodField()
    reviewer_name = serializers.CharField(source='reviewer.display_name', read_only=True, default=None)

    class Meta:
        model = SlipTransaction
        fields = [
            'id', 'status', 'attempt_no', 'amount', 'trans_ref',
            'sending_bank', 'receiving_bank', 'sender_name',
            'slip_file_url', 'amount_matches',
            'order', 'customer', 'merchant',
            'reviewer_name', 'reviewed_at', 'reject_reason', 'created_at',
        ]

    def get_order(self, obj):
        order = obj.order
        if not order:
            return None
        return {
            'id': str(order.id),
            'order_number': order.order_number,
            'total_amount': str(order.total_amount),
            'status': order.status,
            'created_at': order.created_at,
        }

    def get_customer(self, obj):
        customer = obj.order.customer if obj.order_id else None
        if not customer:
            return None
        return {
            'id': str(customer.id),
            'display_name': customer.display_name,
            'phone_number': customer.phone_number,
        }

    def get_merchant(self, obj):
        merchant = obj.order.merchant if obj.order_id else None
        if not merchant:
            return None
        return {'id': str(merchant.id), 'name': merchant.name}

    def get_slip_file_url(self, obj):
        if not obj.slip_image_url:
            return None
        token = make_media_token(obj.id)
        path = reverse('media-slip', kwargs={'slip_id': obj.id, 'token': token})
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(path)
        return path

    def get_amount_matches(self, obj):
        order = obj.order
        if not order:
            return None
        return obj.amount == order.total_amount
