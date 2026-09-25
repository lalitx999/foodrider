import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    UNASSIGNED = 'UNASSIGNED', 'Unassigned'
    CUSTOMER = 'CUSTOMER', 'Customer'
    MERCHANT = 'MERCHANT', 'Merchant'
    RIDER = 'RIDER', 'Rider'
    ADMIN = 'ADMIN', 'Admin'


class ApplicationStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    PENDING_REVIEW = 'PENDING_REVIEW', 'Pending review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'


class RoleChangeStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    CANCELLED = 'CANCELLED', 'Cancelled'


class OnboardingIntentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class User(AbstractUser):
    """
    Custom User Model โดยใช้ UUID เป็น Primary Key
    รองรับ email/password และ Google Identity Services
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True, db_index=True)
    google_user_id = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    display_name = models.CharField(max_length=255)
    picture_url = models.TextField(null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.UNASSIGNED,
        db_index=True
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['display_name']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.display_name} ({self.role})"


class CustomerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='customer_profile')
    default_delivery_address = models.TextField()
    google_maps_url = models.TextField(null=True, blank=True)
    delivery_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    delivery_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customer_profiles'


class OnboardingIntent(models.Model):
    """The role selected in the PWA before a first-time user opens a registration form."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='onboarding_intent')
    selected_role = models.CharField(max_length=20, choices=[
        (UserRole.CUSTOMER.value, UserRole.CUSTOMER.label),
        (UserRole.MERCHANT.value, UserRole.MERCHANT.label),
        (UserRole.RIDER.value, UserRole.RIDER.label),
    ])
    status = models.CharField(max_length=20, choices=OnboardingIntentStatus.choices, default=OnboardingIntentStatus.PENDING, db_index=True)
    selected_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'onboarding_intents'


class MerchantApplication(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='merchant_application')
    store_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    address = models.TextField()
    google_maps_url = models.TextField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    storefront_image = models.ImageField(upload_to='merchant-applications/storefronts/')
    storefront_image_2 = models.ImageField(upload_to='merchant-applications/storefronts/', null=True, blank=True)
    storefront_image_3 = models.ImageField(upload_to='merchant-applications/storefronts/', null=True, blank=True)
    identity_document = models.FileField(upload_to='merchant-applications/identity/', null=True, blank=True)
    bank_account_name = models.CharField(max_length=255, null=True, blank=True)
    bank_account_number = models.CharField(max_length=50, null=True, blank=True)
    bank_name = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True)
    admin_note = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchant_applications'


class MerchantApplicationDocument(models.Model):
    application = models.ForeignKey(MerchantApplication, on_delete=models.CASCADE, related_name='documents')
    document = models.FileField(upload_to='merchant-applications/documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'merchant_application_documents'


class RiderApplication(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='rider_application')
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    vehicle_plate = models.CharField(max_length=50)
    driver_license_image = models.ImageField(upload_to='rider-applications/licenses/')
    vehicle_image = models.ImageField(upload_to='rider-applications/vehicles/')
    additional_document = models.FileField(upload_to='rider-applications/documents/', null=True, blank=True)
    bank_account_name_encrypted = models.TextField(null=True, blank=True)
    bank_account_number_encrypted = models.TextField(null=True, blank=True)
    bank_name_encrypted = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True)
    admin_note = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rider_applications'


class RiderApplicationDocument(models.Model):
    application = models.ForeignKey(RiderApplication, on_delete=models.CASCADE, related_name='documents')
    document = models.FileField(upload_to='rider-applications/documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'rider_application_documents'


class RoleChangeRequest(models.Model):
    """Administrative record for a request to move a user to another active role."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='role_change_requests')
    current_role = models.CharField(max_length=20, choices=UserRole.choices)
    requested_role = models.CharField(
        max_length=20,
        choices=[
            (UserRole.MERCHANT.value, UserRole.MERCHANT.label),
            (UserRole.RIDER.value, UserRole.RIDER.label),
        ],
    )
    merchant_application = models.OneToOneField(
        MerchantApplication,
        on_delete=models.CASCADE,
        related_name='role_change_request',
        null=True,
        blank=True,
    )
    rider_application = models.OneToOneField(
        RiderApplication,
        on_delete=models.CASCADE,
        related_name='role_change_request',
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=20, choices=RoleChangeStatus.choices, default=RoleChangeStatus.PENDING, db_index=True)
    admin_note = models.TextField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_role_change_requests')

    class Meta:
        db_table = 'role_change_requests'
        ordering = ['-requested_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(merchant_application__isnull=False, rider_application__isnull=True)
                    | models.Q(merchant_application__isnull=True, rider_application__isnull=False)
                ),
                name='role_change_request_has_one_application',
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        has_merchant_application = self.merchant_application_id is not None
        has_rider_application = self.rider_application_id is not None
        if has_merchant_application == has_rider_application:
            raise ValidationError('A role-change request must reference exactly one application.')
        if self.requested_role == UserRole.MERCHANT and not has_merchant_application:
            raise ValidationError('Merchant requests must reference a merchant application.')
        if self.requested_role == UserRole.RIDER and not has_rider_application:
            raise ValidationError('Rider requests must reference a rider application.')

    def __str__(self):
        return f'{self.user} {self.current_role} -> {self.requested_role} ({self.status})'
