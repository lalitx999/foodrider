import logging

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
    GoogleVerifySerializer,
    SetRoleSerializer,
    UserProfileSerializer
    , CustomerRegistrationSerializer, MerchantApplicationSerializer, RiderApplicationSerializer,
    ApplicationStatusSerializer
    , EmailRegistrationSerializer, EmailLoginSerializer, SelectOnboardingRoleSerializer
)
from apps.users.models import (
    CustomerProfile, MerchantApplication, MerchantApplicationDocument, RiderApplication, RiderApplicationDocument, ApplicationStatus,
    OnboardingIntent, OnboardingIntentStatus, RoleChangeRequest, RoleChangeStatus,
)
from apps.users.services import (
    verify_google_id_token,
    get_or_create_google_user,
    generate_jwt_tokens,
    register_email_user,
    authenticate_email_user,
    AuthenticationError
)


logger = logging.getLogger(__name__)


class EmailRegistrationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = register_email_user(
            display_name=serializer.validated_data['display_name'],
            email=serializer.validated_data['email'],
            password=serializer.validated_data['password'],
        )
        return Response({'success': True, 'data': generate_jwt_tokens(user), 'message': 'สมัครสมาชิกสำเร็จ'}, status=status.HTTP_201_CREATED)


class EmailLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate_email_user(**serializer.validated_data)
        if not user:
            return Response({'success': False, 'error_code': 'INVALID_CREDENTIALS', 'message': 'อีเมลหรือรหัสผ่านไม่ถูกต้อง', 'details': []}, status=status.HTTP_401_UNAUTHORIZED)
        return Response({'success': True, 'data': generate_jwt_tokens(user), 'message': 'เข้าสู่ระบบสำเร็จ'})


class SelectOnboardingRoleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != UserRole.UNASSIGNED:
            return Response({'success': False, 'error_code': 'ROLE_ALREADY_ASSIGNED', 'message': 'บัญชีนี้มีบทบาทแล้ว', 'details': []}, status=status.HTTP_409_CONFLICT)
        serializer = SelectOnboardingRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        intent, _ = OnboardingIntent.objects.update_or_create(
            user=request.user,
            defaults={'selected_role': serializer.validated_data['role'], 'status': OnboardingIntentStatus.PENDING, 'completed_at': None},
        )
        return Response({'success': True, 'data': {'role': intent.selected_role}, 'message': 'เลือกบทบาทสำเร็จ'})


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
    สลับ Role ของผู้ใช้ (เฉพาะ Admin)
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

        return Response({
            'success': True,
            'data': {
                'user_id': str(user.id),
                'role': user.role,
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
        intent = getattr(request.user, 'onboarding_intent', None)
        if not intent or intent.status != OnboardingIntentStatus.PENDING or intent.selected_role != UserRole.CUSTOMER:
            return Response({'success': False, 'error_code': 'ONBOARDING_INTENT_REQUIRED', 'message': 'กรุณาเลือกบทบาทก่อนเริ่มลงทะเบียน', 'details': []}, status=status.HTTP_409_CONFLICT)
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
                'google_maps_url': data.get('google_maps_url'),
                'delivery_latitude': data.get('delivery_latitude'),
                'delivery_longitude': data.get('delivery_longitude'),
            },
        )
        intent.status = OnboardingIntentStatus.COMPLETED
        intent.completed_at = timezone.now()
        intent.save(update_fields=['status', 'completed_at', 'selected_at'])
        return Response({'success': True, 'message': 'ลงทะเบียนลูกค้าสำเร็จ'}, status=status.HTTP_200_OK)


class MerchantApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        intent = getattr(request.user, 'onboarding_intent', None)
        if not intent or intent.status != OnboardingIntentStatus.PENDING or intent.selected_role != UserRole.MERCHANT:
            return Response({'success': False, 'error_code': 'ONBOARDING_INTENT_REQUIRED', 'message': 'กรุณาเลือกบทบาทก่อนเริ่มลงทะเบียน', 'details': []}, status=status.HTTP_409_CONFLICT)
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

        # Handle additional document uploads
        documents = request.FILES.getlist('additional_documents')
        for doc_file in documents:
            MerchantApplicationDocument.objects.create(
                application=application,
                document=doc_file
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
        intent.status = OnboardingIntentStatus.COMPLETED
        intent.completed_at = timezone.now()
        intent.save(update_fields=['status', 'completed_at', 'selected_at'])
        return Response({'success': True, 'data': {'status': application.status, 'role_change_request_id': role_request.id}, 'message': 'ส่งใบสมัครร้านค้าเพื่อรอตรวจสอบแล้ว'}, status=status.HTTP_201_CREATED)


class RiderApplicationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        intent = getattr(request.user, 'onboarding_intent', None)
        if not intent or intent.status != OnboardingIntentStatus.PENDING or intent.selected_role != UserRole.RIDER:
            return Response({'success': False, 'error_code': 'ONBOARDING_INTENT_REQUIRED', 'message': 'กรุณาเลือกบทบาทก่อนเริ่มลงทะเบียน', 'details': []}, status=status.HTTP_409_CONFLICT)
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

        # Handle additional document uploads
        documents = request.FILES.getlist('additional_documents')
        for doc_file in documents:
            RiderApplicationDocument.objects.create(
                application=application,
                document=doc_file
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
        intent.status = OnboardingIntentStatus.COMPLETED
        intent.completed_at = timezone.now()
        intent.save(update_fields=['status', 'completed_at', 'selected_at'])
        return Response({'success': True, 'data': {'status': application.status, 'role_change_request_id': role_request.id}, 'message': 'ส่งใบสมัครไรเดอร์เพื่อรอตรวจสอบแล้ว'}, status=status.HTTP_201_CREATED)


class RegistrationStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role_request = RoleChangeRequest.objects.filter(user=request.user).order_by('-requested_at').first()

        details = {}
        if hasattr(request.user, 'merchant_application'):
            app = request.user.merchant_application
            details = {
                'title_name': app.store_name,
                'phone_number': app.phone_number,
                'address': app.address,
                'google_maps_url': app.google_maps_url,
                'bank_name': app.bank_name,
                'bank_account_name': app.bank_account_name,
                'bank_account_number': app.bank_account_number,
                'submitted_at': app.submitted_at,
            }
        elif hasattr(request.user, 'rider_application'):
            app = request.user.rider_application
            details = {
                'title_name': app.full_name,
                'phone_number': app.phone_number,
                'vehicle_plate': app.vehicle_plate,
                'submitted_at': app.submitted_at,
            }

        if role_request:
            return Response({'success': True, 'data': {
                'role': role_request.requested_role,
                'status': role_request.status,
                'admin_note': role_request.admin_note,
                'details': details,
            }})
        if hasattr(request.user, 'merchant_application'):
            app = request.user.merchant_application
            return Response({'success': True, 'data': {
                'role': 'MERCHANT',
                'status': app.status,
                'admin_note': app.admin_note,
                'details': details,
            }})
        if hasattr(request.user, 'rider_application'):
            app = request.user.rider_application
            return Response({'success': True, 'data': {
                'role': 'RIDER',
                'status': app.status,
                'admin_note': app.admin_note,
                'details': details,
            }})
        if hasattr(request.user, 'customer_profile'):
            return Response({'success': True, 'data': {
                'role': 'CUSTOMER',
                'status': ApplicationStatus.APPROVED,
                'admin_note': None,
                'details': {},
            }})
        return Response({'success': True, 'data': None})
