import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    CUSTOMER = 'CUSTOMER', 'Customer'
    MERCHANT = 'MERCHANT', 'Merchant'
    RIDER = 'RIDER', 'Rider'
    ADMIN = 'ADMIN', 'Admin'


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
