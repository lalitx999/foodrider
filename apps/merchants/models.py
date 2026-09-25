import uuid
from django.db import models
from django.contrib.gis.db import models as gis_models
from apps.users.models import User


class Merchant(models.Model):
    """
    ตารางข้อมูลร้านค้า (1 User : 1 Merchant)
    รองรับการคำนวณตำแหน่งภูมิศาสตร์ผ่าน PostGIS PointField
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.RESTRICT, related_name='merchant_profile')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    image_url = models.TextField()
    phone_number = models.CharField(max_length=20)
    address = models.TextField()
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    location = gis_models.PointField(srid=4326, null=True, blank=True, spatial_index=True)
    is_open = models.BooleanField(default=False, db_index=True)
    gp_rate = models.DecimalField(max_digits=5, decimal_places=2, default=15.00)
    bank_account_name = models.CharField(max_length=255)
    bank_account_number = models.CharField(max_length=50)
    bank_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'merchants'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} (Open: {self.is_open})"


class Category(models.Model):
    """
    ตารางหมวดหมู่เมนูอาหารของร้านค้า
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'categories'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.merchant.name} - {self.name}"


class MenuItem(models.Model):
    """
    ตารางรายการอาหาร
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    merchant = models.ForeignKey(Merchant, on_delete=models.CASCADE, related_name='menu_items')
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.TextField(null=True, blank=True)
    image = models.ImageField(upload_to='merchant-menus/', null=True, blank=True)
    is_available = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'menu_items'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.price} THB)"


class MenuOption(models.Model):
    """
    ตารางตัวเลือกเสริม (เช่น เพิ่มไข่ดาว, พิเศษ, หวาน 50%)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=100)
    extra_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'menu_options'

    def __str__(self):
        return f"{self.name} (+{self.extra_price} THB)"
