from rest_framework import serializers
from apps.users.models import User, UserRole
from apps.users.bank_encryption import BankDataEncryptionError, encrypt_bank_value
from apps.users.models import CustomerProfile, MerchantApplication, RiderApplication, ApplicationStatus
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


class GoogleVerifySerializer(serializers.Serializer):
    """
    Serializer ตรวจสอบ Payload การส่ง Google ID Token
    """
    id_token = serializers.CharField(
        required=True,
        allow_blank=False,
        error_messages={'required': 'กรุณาระบุ id_token จาก Google'}
    )


class EmailRegistrationSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=12, trim_whitespace=False)
    password_confirm = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({'password_confirm': 'รหัสผ่านไม่ตรงกัน'})
        if User.objects.filter(email__iexact=attrs['email']).exists():
            raise serializers.ValidationError({'email': 'อีเมลนี้ถูกใช้งานแล้ว'})
        try:
            validate_password(attrs['password'])
        except DjangoValidationError as error:
            raise serializers.ValidationError({'password': list(error.messages)}) from error
        return attrs


class EmailLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class SelectOnboardingRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[UserRole.CUSTOMER, UserRole.MERCHANT, UserRole.RIDER])


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
    default_delivery_address = serializers.SerializerMethodField()
    delivery_latitude = serializers.SerializerMethodField()
    delivery_longitude = serializers.SerializerMethodField()

    def _customer_value(self, obj, field):
        profile = getattr(obj, 'customer_profile', None)
        return getattr(profile, field, None) if profile else None

    def get_default_delivery_address(self, obj):
        return self._customer_value(obj, 'default_delivery_address')

    def get_delivery_latitude(self, obj):
        return self._customer_value(obj, 'delivery_latitude')

    def get_delivery_longitude(self, obj):
        return self._customer_value(obj, 'delivery_longitude')

    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'google_user_id',
            'display_name',
            'picture_url',
            'phone_number',
            'role',
            'is_active',
            'created_at',
            'updated_at',
            'default_delivery_address',
            'delivery_latitude',
            'delivery_longitude',
        ]
        read_only_fields = fields


class CustomerRegistrationSerializer(serializers.Serializer):
    display_name = serializers.CharField(max_length=255)
    phone_number = serializers.CharField(max_length=20)
    default_delivery_address = serializers.CharField()
    google_maps_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    delivery_latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    delivery_longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)


class MerchantApplicationSerializer(serializers.ModelSerializer):
    google_maps_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    latitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    longitude = serializers.DecimalField(max_digits=10, decimal_places=7, required=False, allow_null=True)
    storefront_image_2 = serializers.ImageField(required=False, allow_null=True)
    storefront_image_3 = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = MerchantApplication
        fields = [
            'store_name', 'phone_number', 'address', 'google_maps_url', 'latitude', 'longitude',
            'storefront_image', 'storefront_image_2', 'storefront_image_3', 'identity_document',
            'bank_account_name', 'bank_account_number', 'bank_name',
        ]
        extra_kwargs = {
            'storefront_image': {'required': True},
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
