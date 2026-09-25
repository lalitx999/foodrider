import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    CUSTOMER = 'CUSTOMER', 'Customer'
    MERCHANT = 'MERCHANT', 'Merchant'
    RIDER = 'RIDER', 'Rider'
    ADMIN = 'ADMIN', 'Admin'


class ApplicationStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    PENDING_REVIEW = 'PENDING_REVIEW', 'Pending review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'


class User(AbstractUser):
    """
    Custom User Model โดยใช้ UUID เป็น Primary Key
    รองรับการระบุตัวตนคู่ผ่าน LINE User ID และ Google OAuth User ID
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    line_user_id = models.CharField(max_length=64, unique=True, null=True, blank=True, db_index=True)
    google_user_id = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    display_name = models.CharField(max_length=255)
    picture_url = models.TextField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['display_name']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.display_name} ({self.role})"


class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    default_delivery_address = models.TextField()
    delivery_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    delivery_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customer_profiles'


class MerchantApplication(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='merchant_application')
    store_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    address = models.TextField()
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    storefront_image = models.ImageField(upload_to='merchant-applications/storefronts/')
    identity_document = models.FileField(upload_to='merchant-applications/identity/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True)
    admin_note = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_applications'


class RiderApplication(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='rider_application')
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    vehicle_plate = models.CharField(max_length=50)
    driver_license_image = models.ImageField(upload_to='rider-applications/licenses/')
    vehicle_image = models.ImageField(upload_to='rider-applications/vehicles/')
    additional_document = models.FileField(upload_to='rider-applications/documents/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True)
    admin_note = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rider_applications'
