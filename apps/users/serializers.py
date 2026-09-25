from rest_framework import serializers
from apps.users.models import User, UserRole
from apps.users.bank_encryption import BankDataEncryptionError, encrypt_bank_value
from apps.users.models import CustomerProfile, MerchantApplication, RiderApplication, ApplicationStatus


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


class CustomerRegistrationSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
    default_delivery_address = serializers.CharField()
    delivery_latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    delivery_longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)


class MerchantApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = MerchantApplication
        fields = [
            'store_name', 'phone_number', 'address', 'latitude', 'longitude',
            'storefront_image', 'identity_document', 'bank_account_name',
            'bank_account_number', 'bank_name',
        ]
        extra_kwargs = {
            'bank_account_name': {'required': True, 'allow_blank': False},
            'bank_account_number': {'required': True, 'allow_blank': False},
            'bank_name': {'required': True, 'allow_blank': False},
        }


class RiderApplicationSerializer(serializers.ModelSerializer):
    bank_account_name = serializers.CharField(write_only=True, max_length=255)
    bank_account_number = serializers.CharField(write_only=True, max_length=50)
    bank_name = serializers.CharField(write_only=True, max_length=100)

    class Meta:
        model = RiderApplication
        fields = [
            'full_name', 'phone_number', 'vehicle_plate', 'driver_license_image',
            'vehicle_image', 'additional_document', 'bank_account_name',
            'bank_account_number', 'bank_name',
        ]

    def validate(self, attrs):
        try:
            attrs['bank_account_name_encrypted'] = encrypt_bank_value(attrs.pop('bank_account_name'))
            attrs['bank_account_number_encrypted'] = encrypt_bank_value(attrs.pop('bank_account_number'))
            attrs['bank_name_encrypted'] = encrypt_bank_value(attrs.pop('bank_name'))
        except BankDataEncryptionError as error:
            raise serializers.ValidationError({'bank_account_number': str(error)}) from error
        return attrs


class ApplicationStatusSerializer(serializers.Serializer):
    role = serializers.CharField()
    status = serializers.ChoiceField(choices=ApplicationStatus.choices)
    admin_note = serializers.CharField(allow_null=True)
