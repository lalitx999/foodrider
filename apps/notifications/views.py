from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers
from apps.notifications.models import DeviceToken


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
