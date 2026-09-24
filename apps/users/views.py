from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from apps.users.models import User
from apps.users.models import UserRole
from apps.merchants.models import Merchant
from apps.riders.models import RiderProfile
from apps.users.serializers import (
    LineVerifySerializer,
    GoogleVerifySerializer,
    SetRoleSerializer,
    UserProfileSerializer
)
from apps.users.services import (
    verify_line_id_token,
    verify_google_id_token,
    get_or_create_line_user,
    get_or_create_google_user,
    generate_jwt_tokens,
    sync_line_rich_menu,
    AuthenticationError
)


class LineVerifyView(APIView):
    """
    POST /api/v1/auth/line-verify/
    รับ id_token จาก LINE LIFF -> ตรวจสอบ Signature กับ LINE API -> คืนค่า JWT Token
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LineVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        id_token = serializer.validated_data['id_token']

        try:
            line_user_data = verify_line_id_token(id_token)
            user = get_or_create_line_user(line_user_data)
            tokens = generate_jwt_tokens(user)

            return Response({
                'success': True,
                'data': tokens,
                'message': 'ยืนยันตัวตนด้วย LINE สำเร็จ'
            }, status=status.HTTP_200_OK)

        except AuthenticationError as e:
            return Response({
                'success': False,
                'error_code': 'AUTH_INVALID_TOKEN',
                'message': str(e),
                'details': []
            }, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({
                'success': False,
                'error_code': 'INTERNAL_SERVER_ERROR',
                'message': 'เกิดข้อผิดพลาดภายในระบบ',
                'details': [str(e)]
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GoogleVerifyView(APIView):
    """
    POST /api/v1/auth/google-verify/
    รับ id_token จาก Google Auth -> ตรวจสอบ Signature -> คืนค่า JWT Token
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GoogleVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        id_token = serializer.validated_data['id_token']

        try:
            google_user_data = verify_google_id_token(id_token)
            user = get_or_create_google_user(google_user_data)
            tokens = generate_jwt_tokens(user)

            return Response({
                'success': True,
                'data': tokens,
                'message': 'ยืนยันตัวตนด้วย Google สำเร็จ'
            }, status=status.HTTP_200_OK)

        except AuthenticationError as e:
            return Response({
                'success': False,
                'error_code': 'AUTH_INVALID_TOKEN',
                'message': str(e),
                'details': []
            }, status=status.HTTP_401_UNAUTHORIZED)
        except Exception as e:
            return Response({
                'success': False,
                'error_code': 'INTERNAL_SERVER_ERROR',
                'message': 'เกิดข้อผิดพลาดภายในระบบ',
                'details': [str(e)]
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SetRoleView(APIView):
    """
    POST /api/v1/auth/set-role/
    สลับ Role ของผู้ใช้ และยิงไปเปลี่ยน LINE Rich Menu ประจำตัวบุคคลทันที (เฉพาะ Admin)
    """
    permission_classes = [IsAdminUser]

    def post(self, request):
        serializer = SetRoleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error_code': 'INVALID_PAYLOAD',
                'message': 'ข้อมูล Payload ไม่ถูกต้อง',
                'details': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        user_id = serializer.validated_data['user_id']
        new_role = serializer.validated_data['role']

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response({
                'success': False,
                'error_code': 'USER_NOT_FOUND',
                'message': 'ไม่พบผู้ใช้ที่ระบุ',
                'details': []
            }, status=status.HTTP_404_NOT_FOUND)

        if new_role == UserRole.MERCHANT and not Merchant.objects.filter(user=user).exists():
            return Response({
                'success': False,
                'error_code': 'MERCHANT_PROFILE_REQUIRED',
                'message': 'ต้องสร้างโปรไฟล์ร้านค้าและผูกกับผู้ใช้นี้ก่อนกำหนดสิทธิ์ร้านค้า',
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)

        if new_role == UserRole.RIDER and not RiderProfile.objects.filter(user=user).exists():
            return Response({
                'success': False,
                'error_code': 'RIDER_PROFILE_REQUIRED',
                'message': 'ต้องสร้างโปรไฟล์ไรเดอร์และผูกกับผู้ใช้นี้ก่อนกำหนดสิทธิ์ไรเดอร์',
                'details': []
            }, status=status.HTTP_400_BAD_REQUEST)

        user.role = new_role
        user.save()

        # สลับ LINE Rich Menu ประจำตัวบุคคล
        rich_menu_synced = sync_line_rich_menu(user, new_role)

        return Response({
            'success': True,
            'data': {
                'user_id': str(user.id),
                'role': user.role,
                'rich_menu_synced': rich_menu_synced
            },
            'message': f'เปลี่ยน Role เป็น {new_role} สำเร็จ'
        }, status=status.HTTP_200_OK)


class UserProfileView(APIView):
    """
    GET /api/v1/auth/me/
    ดึงข้อมูลโปรไฟล์ผู้ใช้ที่ล็อกอินอยู่ปัจจุบัน
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response({
            'success': True,
            'data': serializer.data,
            'message': 'ดึงข้อมูลโปรไฟล์สำเร็จ'
        }, status=status.HTTP_200_OK)
