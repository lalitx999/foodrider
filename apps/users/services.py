import os
import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from rest_framework_simplejwt.tokens import RefreshToken
from apps.users.models import User, UserRole
from apps.users.models import ApplicationStatus, RoleChangeRequest, RoleChangeStatus


class AuthenticationError(Exception):
    """Custom Exception สำหรับข้อผิดพลาดด้านความปลอดภัยและการยืนยันตัวตน"""
    pass


def verify_line_id_token(id_token: str) -> dict:
    """
    ยิงไปตรวจสอบ Signature ของ LINE ID Token กับ LINE Authorization Endpoint
    เพื่อป้องกันการปลอมแปลง line_user_id จากฝั่ง Frontend (Zero Trust Security)
    """
    line_channel_id = os.environ.get('LINE_CHANNEL_ID')
    verify_url = 'https://api.line.me/oauth2/v2.1/verify'
    
    response = requests.post(verify_url, data={
        'id_token': id_token,
        'client_id': line_channel_id
    }, timeout=10)
    
    if response.status_code != 200:
        raise AuthenticationError("โทเค็น LINE ไม่ถูกต้อง หรือหมดอายุแล้ว")
        
    data = response.json()
    return {
        'line_user_id': data.get('sub'),
        'display_name': data.get('name', 'LINE User'),
        'picture_url': data.get('picture')
    }


def verify_google_id_token(id_token: str) -> dict:
    """
    ตรวจสอบความถูกต้องของ Google ID Token ผ่าน google-auth library
    """
    google_client_id = os.environ.get('GOOGLE_CLIENT_ID')
    try:
        id_info = google_id_token.verify_oauth2_token(
            id_token, 
            google_requests.Request(), 
            google_client_id
        )
        return {
            'google_user_id': id_info.get('sub'),
            'display_name': id_info.get('name', 'Google User'),
            'picture_url': id_info.get('picture'),
            'email': id_info.get('email')
        }
    except ValueError as e:
        raise AuthenticationError(f"โทเค็น Google ไม่ถูกต้อง: {str(e)}")


def get_or_create_line_user(user_data: dict) -> User:
    """
    ดึงข้อมูลผู้ใช้จาก line_user_id หากไม่มีให้สร้างใหม่เป็น UNASSIGNED
    """
    line_user_id = user_data['line_user_id']
    user = User.objects.filter(line_user_id=line_user_id).first()
    
    if not user:
        user = User.objects.create(
            line_user_id=line_user_id,
            display_name=user_data['display_name'],
            picture_url=user_data['picture_url'],
            role=UserRole.UNASSIGNED
        )
    else:
        # อัปเดตข้อมูลโปรไฟล์ล่าสุดจาก LINE
        user.display_name = user_data['display_name']
        if user_data.get('picture_url'):
            user.picture_url = user_data['picture_url']
        user.save()
        
    return user


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
        RiderProfile.objects.get_or_create(user=user, defaults={'vehicle_plate': application.vehicle_plate})
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
    return request


def get_or_create_google_user(user_data: dict) -> User:
    """
    ดึงข้อมูลผู้ใช้จาก google_user_id หากไม่มีให้สร้างใหม่เป็น Role CUSTOMER
    """
    google_user_id = user_data['google_user_id']
    user = User.objects.filter(google_user_id=google_user_id).first()
    
    if not user:
        user = User.objects.create(
            google_user_id=google_user_id,
            display_name=user_data['display_name'],
            picture_url=user_data.get('picture_url'),
            role=UserRole.CUSTOMER
        )
    else:
        user.display_name = user_data['display_name']
        if user_data.get('picture_url'):
            user.picture_url = user_data['picture_url']
        user.save()
        
    return user


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
            'line_user_id': user.line_user_id,
            'google_user_id': user.google_user_id,
        }
    }


def sync_line_rich_menu(user: User, new_role: str) -> bool:
    """
    ยิงไปที่ LINE Messaging API เพื่อเปลี่ยน Rich Menu ประจำตัวบุคคลตาม Role
    """
    if not user.line_user_id:
        return False
        
    access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not access_token:
        return False
        
    rich_menu_mapping = {
        UserRole.CUSTOMER: os.environ.get('LINE_RICH_MENU_CUSTOMER'),
        UserRole.MERCHANT: os.environ.get('LINE_RICH_MENU_MERCHANT'),
        UserRole.RIDER: os.environ.get('LINE_RICH_MENU_RIDER'),
    }
    
    rich_menu_id = rich_menu_mapping.get(new_role)
    if not rich_menu_id:
        return False
        
    url = f"https://api.line.me/v2/bot/user/{user.line_user_id}/richmenu/{rich_menu_id}"
    headers = {'Authorization': f"Bearer {access_token}"}
    
    try:
        response = requests.post(url, headers=headers, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False
