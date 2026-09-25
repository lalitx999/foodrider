import uuid
from django.db import models
from django.contrib.gis.db import models as gis_models
from apps.users.models import User


class RiderProfile(models.Model):
    """
    ตารางข้อมูลโปรไฟล์ไรเดอร์ (1 User : 1 Rider Profile)
    เก็บสถานะเปิดรับงาน พิกัดปัจจุบัน และยอดเงินสะสมในกระเป๋าเงิน (Wallet)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='rider_profile')
    vehicle_plate = models.CharField(max_length=50)
    is_online = models.BooleanField(default=False, db_index=True)
    current_latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    current_location = gis_models.PointField(srid=4326, null=True, blank=True, spatial_index=True)
    wallet_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    bank_account_name_encrypted = models.TextField(null=True, blank=True)
    bank_account_number_encrypted = models.TextField(null=True, blank=True)
    bank_name_encrypted = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rider_profiles'

    def __str__(self):
        return f"Rider: {self.user.display_name} - Plate: {self.vehicle_plate} (Online: {self.is_online})"
