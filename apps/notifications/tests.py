import base64
import hashlib
import hmac
import json
import os
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from apps.users.models import User, UserRole
from apps.orders.models import Order, OrderStatus
from apps.merchants.models import Merchant
from apps.notifications.models import DeviceToken, ProcessedLineWebhookEvent
from apps.notifications.services import build_order_status_flex_message


class NotificationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(display_name='Notification User', role=UserRole.CUSTOMER)
        self.register_url = reverse('register-device')
        self.webhook_url = reverse('line-webhook')

    def test_register_device_token(self):
        """ทดสอบลงทะเบียน FCM Device Token"""
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.register_url, {'fcm_token': 'fcm_test_token_12345'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['success'])
        self.assertTrue(DeviceToken.objects.filter(user=self.user, fcm_token='fcm_test_token_12345').exists())

    def test_build_order_status_flex_message(self):
        """ทดสอบการสร้างโครงสร้าง LINE Flex Message การ์ดสีเขียว #689D4B"""
        merchant_user = User.objects.create(display_name='Merchant Owner', role=UserRole.MERCHANT)
        merchant = Merchant.objects.create(
            user=merchant_user,
            name='ร้านอาหารตัวอย่าง',
            image_url='https://example.com/img.jpg',
            phone_number='0811111111',
            address='เชียงใหม่',
            latitude=18.78,
            longitude=98.98,
            is_open=True,
            bank_account_name='A',
            bank_account_number='1',
            bank_name='B'
        )

        order = Order.objects.create(
            order_number='ORD-FLEX-1',
            customer=self.user,
            merchant=merchant,
            status=OrderStatus.PAID,
            subtotal=100.00,
            delivery_fee=20.00,
            total_amount=120.00,
            delivery_address='ที่อยู่',
            delivery_latitude=18.78,
            delivery_longitude=98.98,
            delivery_distance_km=1.0,
            rider_delivery_fee=17.00,
            platform_fee=15.00
        )

        flex_dict = build_order_status_flex_message(order)
        self.assertEqual(flex_dict['type'], 'bubble')
        self.assertEqual(flex_dict['header']['backgroundColor'], '#689D4B')
        self.assertIn('ORD-FLEX-1', flex_dict['header']['contents'][1]['text'])

    @patch.dict(os.environ, {'LINE_CHANNEL_SECRET': 'test-channel-secret'}, clear=False)
    def test_line_webhook_rejects_invalid_signature(self):
        response = self.client.generic(
            'POST',
            self.webhook_url,
            data=b'{"events": []}',
            content_type='application/json',
            HTTP_X_LINE_SIGNATURE='invalid-signature',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(ProcessedLineWebhookEvent.objects.count(), 0)

    @patch('apps.notifications.services.reply_line_flex_message', return_value=True)
    @patch.dict(os.environ, {'LINE_CHANNEL_SECRET': 'test-channel-secret'}, clear=False)
    def test_line_webhook_ignores_redelivered_event(self, mock_reply):
        payload = {
            'events': [{
                'webhookEventId': '01HWEBHOOKEVENTIDTEST00000001',
                'type': 'message',
                'replyToken': 'reply-token',
                'source': {'userId': 'Utest'},
                'message': {'type': 'text', 'text': 'สั่งอาหาร'},
            }]
        }
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        signature = base64.b64encode(
            hmac.new(b'test-channel-secret', body, hashlib.sha256).digest()
        ).decode('utf-8')

        for _ in range(2):
            response = self.client.generic(
                'POST',
                self.webhook_url,
                data=body,
                content_type='application/json',
                HTTP_X_LINE_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(mock_reply.call_count, 1)
        self.assertEqual(ProcessedLineWebhookEvent.objects.count(), 1)
