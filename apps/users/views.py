from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from django.utils import timezone
from apps.users.models import User
from apps.users.models import UserRole
from apps.merchants.models import Merchant
from apps.riders.models import RiderProfile
from apps.users.serializers import (
    LineVerifySerializer,
    GoogleVerifySerializer,
    SetRoleSerializer,
    UserProfileSerializer
    , CustomerRegistrationSerializer, MerchantApplicationSerializer, RiderApplicationSerializer,
    ApplicationStatusSerializer
)
from apps.users.models import (
    CustomerProfile, MerchantApplication, RiderApplication, ApplicationStatus,
    RoleChangeRequest, RoleChangeStatus,
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


class CustomerRegistrationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role not in {UserRole.UNASSIGNED, UserRole.CUSTOMER}:
            return Response({
                'success': False,
                'error_code': 'ROLE_CHANGE_REQUIRED',
                'message': 'บัญชีนี้มีบทบาทอื่นอยู่ กรุณายื่นคำขอเปลี่ยนบทบาทผ่านระบบ',
                'details': [],
            }, status=status.HTTP_409_CONFLICT)
        serializer = CustomerRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        request.user.display_name = data['display_name']
        request.user.phone_number = data['phone_number']
        request.user.role = UserRole.CUSTOMER
        request.user.save()
        CustomerProfile.objects.update_or_create(
            user=request.user,
            defaults={
                'default_delivery_address': data['default_delivery_address'],
                'delivery_latitude': data.get('delivery_latitude'),
                'delivery_longitude': data.get('delivery_longitude'),
            },
        )
        return Response({'success': True, 'message': 'ลงทะเบียนลูกค้าสำเร็จ'}, status=status.HTTP_200_OK)


class MerchantApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pending_request = RoleChangeRequest.objects.filter(
            user=request.user,
            status=RoleChangeStatus.PENDING,
        ).exclude(requested_role=UserRole.MERCHANT).exists()
        if pending_request:
            return Response({
                'success': False,
                'error_code': 'ROLE_CHANGE_ALREADY_PENDING',
                'message': 'มีคำขอเปลี่ยนบทบาทอื่นที่กำลังรอการตรวจสอบ',
                'details': [],
            }, status=status.HTTP_409_CONFLICT)
        serializer = MerchantApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application, _ = MerchantApplication.objects.update_or_create(
            user=request.user,
            defaults={**serializer.validated_data, 'status': ApplicationStatus.PENDING_REVIEW, 'submitted_at': timezone.now(), 'admin_note': None},
        )
        role_request, _ = RoleChangeRequest.objects.update_or_create(
            merchant_application=application,
            defaults={
                'user': request.user,
                'current_role': request.user.role,
                'requested_role': UserRole.MERCHANT,
                'rider_application': None,
                'status': RoleChangeStatus.PENDING,
                'admin_note': None,
                'reviewed_by': None,
                'reviewed_at': None,
            },
        )
        return Response({'success': True, 'data': {'status': application.status, 'role_change_request_id': role_request.id}, 'message': 'ส่งใบสมัครร้านค้าเพื่อรอตรวจสอบแล้ว'}, status=status.HTTP_201_CREATED)


class RiderApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pending_request = RoleChangeRequest.objects.filter(
            user=request.user,
            status=RoleChangeStatus.PENDING,
        ).exclude(requested_role=UserRole.RIDER).exists()
        if pending_request:
            return Response({
                'success': False,
                'error_code': 'ROLE_CHANGE_ALREADY_PENDING',
                'message': 'มีคำขอเปลี่ยนบทบาทอื่นที่กำลังรอการตรวจสอบ',
                'details': [],
            }, status=status.HTTP_409_CONFLICT)
        serializer = RiderApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application, _ = RiderApplication.objects.update_or_create(
            user=request.user,
            defaults={**serializer.validated_data, 'status': ApplicationStatus.PENDING_REVIEW, 'submitted_at': timezone.now(), 'admin_note': None},
        )
        role_request, _ = RoleChangeRequest.objects.update_or_create(
            rider_application=application,
            defaults={
                'user': request.user,
                'current_role': request.user.role,
                'requested_role': UserRole.RIDER,
                'merchant_application': None,
                'status': RoleChangeStatus.PENDING,
                'admin_note': None,
                'reviewed_by': None,
                'reviewed_at': None,
            },
        )
        return Response({'success': True, 'data': {'status': application.status, 'role_change_request_id': role_request.id}, 'message': 'ส่งใบสมัครไรเดอร์เพื่อรอตรวจสอบแล้ว'}, status=status.HTTP_201_CREATED)


class RegistrationStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role_request = RoleChangeRequest.objects.filter(user=request.user).order_by('-requested_at').first()
        if role_request:
            return Response({'success': True, 'data': {
                'role': role_request.requested_role,
                'status': role_request.status,
                'admin_note': role_request.admin_note,
            }})
        if hasattr(request.user, 'merchant_application'):
            application = request.user.merchant_application
            return Response({'success': True, 'data': {'role': 'MERCHANT', 'status': application.status, 'admin_note': application.admin_note}})
        if hasattr(request.user, 'rider_application'):
            application = request.user.rider_application
            return Response({'success': True, 'data': {'role': 'RIDER', 'status': application.status, 'admin_note': application.admin_note}})
        if hasattr(request.user, 'customer_profile'):
            return Response({'success': True, 'data': {'role': 'CUSTOMER', 'status': ApplicationStatus.APPROVED, 'admin_note': None}})
        return Response({'success': True, 'data': None})
