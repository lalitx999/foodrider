from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.notifications.models import DeviceToken, Notification


class RegisterDeviceTokenSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(max_length=4096)


class RegisterDeviceTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = RegisterDeviceTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DeviceToken.objects.update_or_create(
            fcm_token=serializer.validated_data['fcm_token'],
            defaults={'user': request.user, 'is_active': True},
        )
        return Response({'success': True, 'message': 'ลงทะเบียนอุปกรณ์สำหรับการแจ้งเตือนแล้ว'})


class UnregisterDeviceTokensView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        DeviceToken.objects.filter(user=request.user).update(is_active=False)
        return Response({'success': True, 'message': 'ปิดการแจ้งเตือนของบัญชีนี้บนอุปกรณ์แล้ว'})


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = Notification.objects.filter(user=request.user)[:50]
        data = [{'id': str(item.id), 'title': item.title, 'body': item.body, 'data': item.data, 'created_at': item.created_at} for item in items]
        return Response({'success': True, 'data': data})
