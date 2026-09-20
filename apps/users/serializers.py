from rest_framework import serializers
from apps.users.models import User, UserRole


class LineVerifySerializer(serializers.Serializer):
    """
    Serializer ตรวจสอบ Payload การส่ง LINE ID Token
    """
    id_token = serializers.CharField(
        required=True,
        allow_blank=False,
        error_messages={'required': 'กรุณาระบุ id_token จาก LINE'}
    )


class GoogleVerifySerializer(serializers.Serializer):
    """
    Serializer ตรวจสอบ Payload การส่ง Google ID Token
    """
    id_token = serializers.CharField(
        required=True,
        allow_blank=False,
        error_messages={'required': 'กรุณาระบุ id_token จาก Google'}
    )


class SetRoleSerializer(serializers.Serializer):
    """
    Serializer สำหรับเปลี่ยน Role ของผู้ใช้ (เฉพาะ Admin)
    """
    user_id = serializers.UUIDField(
        required=True,
        error_messages={'required': 'กรุณาระบุ user_id'}
    )
    role = serializers.ChoiceField(
        choices=UserRole.choices,
        required=True,
        error_messages={'required': 'กรุณาระบุ role ที่ถูกต้อง'}
    )


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Serializer สำหรับแสดงผลข้อมูลโปรไฟล์ผู้ใช้
    """
    class Meta:
        model = User
        fields = [
            'id',
            'line_user_id',
            'google_user_id',
            'display_name',
            'picture_url',
            'phone_number',
            'role',
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = fields
