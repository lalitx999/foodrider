import os
import hmac
import hashlib
import base64
import json
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import serializers
from apps.notifications.models import DeviceToken, ProcessedLineWebhookEvent

logger = logging.getLogger(__name__)


class RegisterDeviceTokenSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(required=True)


class RegisterDeviceTokenView(APIView):
    """
    POST /api/v1/notifications/register-device/
    ลงทะเบียน FCM Token สำหรับรับการแจ้งเตือน Web Push บน PWA
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RegisterDeviceTokenSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'กรุณาระบุ fcm_token',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        fcm_token = serializer.validated_data['fcm_token']
        device, created = DeviceToken.objects.get_or_create(
            user=request.user,
            fcm_token=fcm_token
        )

        return Response({
            'success': True,
            'data': {
                'token_id': str(device.id),
                'fcm_token': device.fcm_token
            },
            'message': 'ลงทะเบียน FCM Token สำหรับรับการแจ้งเตือนเรียบร้อยแล้ว'
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class LineWebhookView(APIView):
    """
    POST /api/v1/notifications/line-webhook/
    รับ Webhook Events จาก LINE Platform พร้อมตรวจสอบความปลอดภัย X-Line-Signature (HMAC-SHA256)
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return Response({
            'status': 'ok',
            'message': 'LINE Webhook endpoint is active. Please use HTTP POST for LINE Webhook events.'
        }, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        signature = request.headers.get('X-Line-Signature', '')
        channel_secret = os.environ.get('LINE_CHANNEL_SECRET', '').strip()

        body = request.body

        # Never process an event unless it can be proven to originate from LINE.
        # An empty secret is a configuration error, not a development bypass.
        if not channel_secret:
            logger.error('LINE webhook rejected because LINE_CHANNEL_SECRET is not configured.')
            return Response(
                {'status': 'error', 'message': 'Webhook authentication is not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not signature:
            logger.warning('LINE webhook rejected because X-Line-Signature is missing.')
            return Response(
                {'status': 'error', 'message': 'Missing webhook signature.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        hash_val = hmac.new(channel_secret.encode('utf-8'), body, hashlib.sha256).digest()
        expected_signature = base64.b64encode(hash_val).decode('utf-8')
        if not hmac.compare_digest(signature, expected_signature):
            logger.warning('LINE webhook rejected because its signature is invalid.')
            return Response(
                {'status': 'error', 'message': 'Invalid webhook signature.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Response(
                {'status': 'error', 'message': 'Invalid JSON payload.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        events = payload.get('events', [])

        if not isinstance(events, list):
            return Response(
                {'status': 'error', 'message': 'Invalid events payload.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ประมวลผล Webhook Events ตามปกติ
        for event in events:
            webhook_event_id = event.get('webhookEventId')
            if webhook_event_id:
                _, created = ProcessedLineWebhookEvent.objects.get_or_create(
                    webhook_event_id=webhook_event_id
                )
                if not created:
                    logger.info('Ignoring redelivered LINE webhook event: %s', webhook_event_id)
                    continue

            event_type = event.get('type')
            source = event.get('source', {})
            line_user_id = source.get('userId')

            if event_type == 'follow':
                logger.info(f"LINE User Followed: {line_user_id}")
            elif event_type == 'unfollow':
                logger.info(f"LINE User Unfollowed: {line_user_id}")
            elif event_type == 'message':
                reply_token = event.get('replyToken')
                message_obj = event.get('message', {})
                msg_type = message_obj.get('type')

                if reply_token and msg_type == 'text':
                    user_text = message_obj.get('text', '').strip().lower()
                    from apps.notifications.services import (
                        reply_line_flex_message,
                        build_customer_command_flex,
                        build_merchant_command_flex,
                        build_rider_command_flex,
                        build_welcome_menu_flex
                    )

                    # สั่งอาหาร / ลูกค้า
                    if any(k in user_text for k in ['สั่งอาหาร', 'สั่งซื้อ', 'ร้านอาหาร', 'ดูเมนู', 'ช้อปปิ้ง', 'customer']):
                        flex_contents = build_customer_command_flex()
                        reply_line_flex_message(reply_token, flex_contents, alt_text='เลือกดูเมนูและสั่งอาหารออนไลน์')

                    # เปิดร้าน / ปิดร้าน / ร้านค้า
                    elif any(k in user_text for k in ['เปิดร้าน', 'ปิดร้าน', 'จัดการร้าน', 'kds', 'merchant', 'ห้องครัว']):
                        action = 'CLOSE' if 'ปิดร้าน' in user_text else 'OPEN'
                        flex_contents = build_merchant_command_flex(action)
                        reply_line_flex_message(reply_token, flex_contents, alt_text=f"{'เปิดร้านรับออเดอร์' if action == 'OPEN' else 'ปิดร้านชั่วคราว'}")

                    # เปิดงาน / ปิดงาน / ไรเดอร์
                    elif any(k in user_text for k in ['เปิดงาน', 'ปิดงาน', 'ส่งอาหาร', 'สแตนด์บาย', 'ไรเดอร์', 'rider']):
                        action = 'CLOSE' if 'ปิดงาน' in user_text else 'OPEN'
                        flex_contents = build_rider_command_flex(action)
                        reply_line_flex_message(reply_token, flex_contents, alt_text=f"{'เปิดงานรับออเดอร์' if action == 'OPEN' else 'พักงานชั่วคราว'}")

                    # เมนูต้อนรับทั่วไป
                    else:
                        flex_contents = build_welcome_menu_flex()
                        reply_line_flex_message(reply_token, flex_contents, alt_text='เลือกเมนูการใช้งานตามบทบาท Food Delivery')

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)
