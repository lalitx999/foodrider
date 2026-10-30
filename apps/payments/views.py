import mimetypes

from django.conf import settings
from django.core import signing
from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.payments.models import SlipTransaction
from apps.payments.storage import resolve_slip_file
from apps.users.media_tokens import read_media_token


class SlipFileView(APIView):
    """
    GET /api/v1/media/slip/<uuid:slip_id>/<str:token>/
    stream ไฟล์สลิปด้วย signed token (ไม่ต้องใช้ header) — ใช้ใน <img> ของ customer/admin
    ไฟล์เก็บนอก MEDIA_ROOT (P0-05/P0-11) → เข้าถึงได้เฉพาะ endpoint นี้
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'media'

    def get(self, request, slip_id, token):
        try:
            payload = read_media_token(token)
        except signing.SignatureExpired:
            return Response({
                'success': False,
                'error_code': 'MEDIA_TOKEN_EXPIRED',
                'message': 'ลิงก์ไฟล์หมดอายุ กรุณาโหลดหน้าใหม่',
                'details': [],
            }, status=status.HTTP_403_FORBIDDEN)
        except signing.BadSignature:
            return Response({
                'success': False,
                'error_code': 'MEDIA_TOKEN_INVALID',
                'message': 'ลิงก์ไฟล์ไม่ถูกต้อง',
                'details': [],
            }, status=status.HTTP_403_FORBIDDEN)

        if str(payload.get('id')) != str(slip_id):
            return Response({
                'success': False,
                'error_code': 'MEDIA_TOKEN_INVALID',
                'message': 'ลิงก์ไฟล์ไม่ถูกต้อง',
                'details': [],
            }, status=status.HTTP_403_FORBIDDEN)

        slip = SlipTransaction.objects.filter(pk=slip_id).only('slip_image_url').first()
        if not slip or not slip.slip_image_url:
            return Response({
                'success': False,
                'error_code': 'SLIP_NOT_FOUND',
                'message': 'ไม่พบไฟล์สลิปที่ระบุ',
                'details': [],
            }, status=status.HTTP_404_NOT_FOUND)

        storage, name = resolve_slip_file(slip.slip_image_url)
        if not name or not storage.exists(name):
            return Response({
                'success': False,
                'error_code': 'SLIP_FILE_MISSING',
                'message': 'ไม่พบไฟล์สลิปในระบบจัดเก็บ',
                'details': [],
            }, status=status.HTTP_404_NOT_FOUND)

        content_type, _ = mimetypes.guess_type(name)
        content_type = content_type or 'application/octet-stream'

        if getattr(settings, 'USE_X_ACCEL_REDIRECT', False):
            # production: ให้ nginx เสิร์ฟไฟล์จาก internal location (ไม่เปิด public /media)
            response = HttpResponse(content_type=content_type)
            response['X-Accel-Redirect'] = f"{settings.X_ACCEL_REDIRECT_PREFIX}{name}"
            response['Content-Disposition'] = 'inline'
            return response

        return FileResponse(storage.open(name, 'rb'), content_type=content_type)
