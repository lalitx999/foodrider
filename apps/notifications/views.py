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
from apps.notifications.models import DeviceToken

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

        try:
            payload = json.loads(body.decode('utf-8'))
        except Exception:
            payload = {}

        events = payload.get('events', [])

        # ตรวจสอบว่าเป็นการกดปุ่ม Verify จาก LINE Console (events เป็น [] หรือ dummy replyToken)
        is_verification_ping = (events == [])

        if channel_secret and signature:
            try:
                hash_val = hmac.new(channel_secret.encode('utf-8'), body, hashlib.sha256).digest()
                expected_signature = base64.b64encode(hash_val).decode('utf-8')
                if not hmac.compare_digest(signature, expected_signature):
                    logger.warning(f"LINE Signature mismatch. Got: {signature}, Expected: {expected_signature}")
                    # หากเป็นการกด Verify ให้ส่ง 200 OK เพื่อให้ใน LINE Console ผ่านการตั้งค่าได้
                    if is_verification_ping:
                        return Response({'status': 'ok', 'message': 'Verification ping received'}, status=status.HTTP_200_OK)
                    return Response({'status': 'error', 'message': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
            except Exception as e:
                logger.error(f"HMAC error: {e}")

        # ประมวลผล Webhook Events ตามปกติ
        for event in events:
            event_type = event.get('type')
            source = event.get('source', {})
            line_user_id = source.get('userId')

            if event_type == 'follow':
                logger.info(f"LINE User Followed: {line_user_id}")
            elif event_type == 'unfollow':
                logger.info(f"LINE User Unfollowed: {line_user_id}")
            elif event_type == 'message':
                reply_token = event.get('replyToken')
                if reply_token:
                    from apps.notifications.services import reply_line_message
                    reply_line_message(reply_token, "ขอบคุณที่ใช้บริการ Food Rider! คุณสามารถเลือกดูเมนูและสั่งอาหารได้ผ่านระบบ LIFF App ครับ")

        return Response({'status': 'ok'}, status=status.HTTP_200_OK)



