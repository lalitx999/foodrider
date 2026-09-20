import os
import requests
from django.conf import settings
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
from rest_framework_simplejwt.tokens import RefreshToken
from apps.users.models import User, UserRole


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
    ดึงข้อมูลผู้ใช้จาก line_user_id หากไม่มีให้สร้างใหม่เป็น Role CUSTOMER
    """
    line_user_id = user_data['line_user_id']
    user = User.objects.filter(line_user_id=line_user_id).first()
    
    if not user:
        user = User.objects.create(
            line_user_id=line_user_id,
            display_name=user_data['display_name'],
            picture_url=user_data['picture_url'],
            role=UserRole.CUSTOMER
        )
    else:
        # อัปเดตข้อมูลโปรไฟล์ล่าสุดจาก LINE
        user.display_name = user_data['display_name']
        if user_data.get('picture_url'):
            user.picture_url = user_data['picture_url']
        user.save()
        
    return user


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
