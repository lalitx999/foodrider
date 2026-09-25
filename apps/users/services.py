import os
from django.contrib.auth import authenticate
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from rest_framework_simplejwt.tokens import RefreshToken
from apps.users.models import User, UserRole
from apps.users.models import ApplicationStatus, RoleChangeRequest, RoleChangeStatus


class AuthenticationError(Exception):
    """Custom Exception สำหรับข้อผิดพลาดด้านความปลอดภัยและการยืนยันตัวตน"""
    pass


def verify_google_id_token(id_token: str) -> dict:
    """
    ตรวจสอบความถูกต้องของ Google ID Token ผ่าน google-auth library
    """
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID')
    if not google_client_id:
        raise AuthenticationError('ยังไม่ได้ตั้งค่า GOOGLE_CLIENT_ID ที่ Backend')
    try:
        id_info = google_id_token.verify_oauth2_token(
            id_token, 
            google_requests.Request(), 
            google_client_id
        )
        if not id_info.get('email_verified'):
            raise AuthenticationError('บัญชี Google นี้ยังไม่ได้ยืนยันอีเมล')
        return {
            'google_user_id': id_info.get('sub'),
            'display_name': id_info.get('name', 'Google User'),
            'picture_url': id_info.get('picture'),
            'email': id_info.get('email')
        }
    except ValueError as e:
        raise AuthenticationError(f"โทเค็น Google ไม่ถูกต้อง: {str(e)}")


class RoleChangeApprovalError(Exception):
    pass


@transaction.atomic
def approve_role_change_request(request_id, reviewer: User, admin_note: str = '') -> RoleChangeRequest:
    """Create the required role profile and switch the user's sole active role atomically."""
    request = RoleChangeRequest.objects.select_for_update().select_related(
        'user', 'merchant_application', 'rider_application'
    ).get(id=request_id)
    user = User.objects.select_for_update().get(id=request.user_id)

    if request.status != RoleChangeStatus.PENDING:
        raise RoleChangeApprovalError('คำขอนี้ไม่ได้อยู่ในสถานะรออนุมัติ')
    if user.role != request.current_role:
        raise RoleChangeApprovalError('บทบาทปัจจุบันของผู้ใช้เปลี่ยนไปแล้ว กรุณาตรวจสอบคำขอใหม่')

    if request.requested_role == UserRole.MERCHANT:
        application = request.merchant_application
        if not application or application.status != ApplicationStatus.PENDING_REVIEW:
            raise RoleChangeApprovalError('ไม่พบใบสมัครร้านค้าที่พร้อมอนุมัติ')
        if not all([application.bank_account_name, application.bank_account_number, application.bank_name]):
            raise RoleChangeApprovalError('ใบสมัครร้านค้ายังขาดข้อมูลบัญชีรับเงิน')
        from apps.merchants.models import Merchant
        Merchant.objects.get_or_create(
            user=user,
            defaults={
                'name': application.store_name,
                'image_url': application.storefront_image.url,
                'phone_number': application.phone_number,
                'address': application.address,
                'latitude': application.latitude,
                'longitude': application.longitude,
                'location': Point(application.longitude, application.latitude, srid=4326),
                'bank_account_name': application.bank_account_name,
                'bank_account_number': application.bank_account_number,
                'bank_name': application.bank_name,
            },
        )
        application.status = ApplicationStatus.APPROVED
        application.admin_note = admin_note or None
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'admin_note', 'reviewed_at', 'updated_at'])
    elif request.requested_role == UserRole.RIDER:
        application = request.rider_application
        if not application or application.status != ApplicationStatus.PENDING_REVIEW:
            raise RoleChangeApprovalError('ไม่พบใบสมัครไรเดอร์ที่พร้อมอนุมัติ')
        from apps.riders.models import RiderProfile
        RiderProfile.objects.get_or_create(
            user=user,
            defaults={
                'vehicle_plate': application.vehicle_plate,
                'bank_account_name_encrypted': application.bank_account_name_encrypted,
                'bank_account_number_encrypted': application.bank_account_number_encrypted,
                'bank_name_encrypted': application.bank_name_encrypted,
            },
        )
        application.status = ApplicationStatus.APPROVED
        application.admin_note = admin_note or None
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'admin_note', 'reviewed_at', 'updated_at'])
    else:
        raise RoleChangeApprovalError('บทบาทที่ขอไม่รองรับ')

    user.role = request.requested_role
    user.save(update_fields=['role', 'updated_at'])
    request.status = RoleChangeStatus.APPROVED
    request.admin_note = admin_note or None
    request.reviewed_by = reviewer
    request.reviewed_at = timezone.now()
    request.save(update_fields=['status', 'admin_note', 'reviewed_by', 'reviewed_at'])
    transaction.on_commit(lambda: __import__('apps.notifications.fcm', fromlist=['create_and_send_notification']).create_and_send_notification(
        user=user,
        title='อนุมัติการสมัครแล้ว',
        body=f'บัญชี{request.get_requested_role_display()}ของคุณได้รับการอนุมัติแล้ว',
        data={'type': 'ROLE_APPROVED', 'role': request.requested_role},
    ))
    return request


@transaction.atomic
def reject_role_change_request(request_id, reviewer: User, admin_note: str) -> RoleChangeRequest:
    if not admin_note.strip():
        raise RoleChangeApprovalError('กรุณาระบุเหตุผลการไม่อนุมัติ')
    request = RoleChangeRequest.objects.select_for_update().select_related(
        'merchant_application', 'rider_application'
    ).get(id=request_id)
    if request.status != RoleChangeStatus.PENDING:
        raise RoleChangeApprovalError('คำขอนี้ไม่ได้อยู่ในสถานะรออนุมัติ')
    application = request.merchant_application or request.rider_application
    if application:
        application.status = ApplicationStatus.REJECTED
        application.admin_note = admin_note
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'admin_note', 'reviewed_at', 'updated_at'])
    request.status = RoleChangeStatus.REJECTED
    request.admin_note = admin_note
    request.reviewed_by = reviewer
    request.reviewed_at = timezone.now()
    request.save(update_fields=['status', 'admin_note', 'reviewed_by', 'reviewed_at'])
    transaction.on_commit(lambda: __import__('apps.notifications.fcm', fromlist=['create_and_send_notification']).create_and_send_notification(
        user=request.user,
        title='ผลการตรวจสอบใบสมัคร',
        body=f'ใบสมัคร{request.get_requested_role_display()}ของคุณยังไม่ได้รับการอนุมัติ: {admin_note}',
        data={'type': 'ROLE_REJECTED', 'role': request.requested_role},
    ))
    return request


def get_or_create_google_user(user_data: dict) -> User:
    """
    ดึงข้อมูลผู้ใช้จาก google_user_id หรือ verified email หากไม่มีให้สร้างใหม่
    """
    google_user_id = user_data['google_user_id']
    user = User.objects.filter(google_user_id=google_user_id).first()
    if not user and user_data.get('email'):
        user = User.objects.filter(email__iexact=user_data['email']).first()
    
    if not user:
        user = User.objects.create(
            google_user_id=google_user_id,
            email=user_data['email'].lower(),
            display_name=user_data['display_name'],
            picture_url=user_data.get('picture_url'),
            role=UserRole.UNASSIGNED
        )
    else:
        user.google_user_id = google_user_id
        user.display_name = user_data['display_name']
        if user_data.get('picture_url'):
            user.picture_url = user_data['picture_url']
        user.save()
        
    return user


def register_email_user(*, display_name: str, email: str, password: str) -> User:
    user = User(email=email.lower(), display_name=display_name, role=UserRole.UNASSIGNED)
    user.set_password(password)
    user.save()
    return user


def authenticate_email_user(*, email: str, password: str) -> User | None:
    return authenticate(username=email.lower(), password=password)


def generate_jwt_tokens(user: User) -> dict:
    """
    สร้าง JWT Access และ Refresh Token สำหรับ Session ของผู้ใช้
    """
    refresh = RefreshToken.for_user(user)
    # แนบข้อมูล role ลงใน Token Payload
    refresh['role'] = user.role
    refresh['display_name'] = user.display_name
    
    return {
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'user': {
            'id': str(user.id),
            'display_name': user.display_name,
            'picture_url': user.picture_url,
            'role': user.role,
            'email': user.email,
            'google_user_id': user.google_user_id,
        }
    }
