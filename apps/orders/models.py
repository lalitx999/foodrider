import uuid
from django.db import models
from django.contrib.gis.db import models as gis_models
from apps.users.models import User
from apps.merchants.models import Merchant, MenuItem


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = 'PENDING_PAYMENT', 'Pending Payment'
    PAID = 'PAID', 'Paid'
    PREPARING = 'PREPARING', 'Preparing'
    READY_FOR_PICKUP = 'READY_FOR_PICKUP', 'Ready for Pickup'
    DELIVERING = 'DELIVERING', 'Delivering'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class Order(models.Model):
    """
    ตารางคำสั่งซื้อ (Order Master Table)
    เก็บประวัติและสถานะออเดอร์ทั้งหมด ห้ามลบข้อมูลเพื่อความถูกต้องทางบัญชี (No Hard Delete)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=32, unique=True, db_index=True)
    customer = models.ForeignKey(User, on_delete=models.RESTRICT, related_name='customer_orders')
    merchant = models.ForeignKey(Merchant, on_delete=models.RESTRICT, related_name='merchant_orders')
    rider = models.ForeignKey(User, on_delete=models.RESTRICT, null=True, blank=True, related_name='rider_orders', db_index=True)
    status = models.CharField(
        max_length=30,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING_PAYMENT,
        db_index=True
    )
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    delivery_address = models.TextField()
    delivery_latitude = models.DecimalField(max_digits=10, decimal_places=7)
    delivery_longitude = models.DecimalField(max_digits=10, decimal_places=7)
    delivery_location = gis_models.PointField(srid=4326, null=True, blank=True, spatial_index=True)
    delivery_distance_km = models.DecimalField(max_digits=6, decimal_places=2)
    note_to_merchant = models.TextField(null=True, blank=True)
    rider_delivery_fee = models.DecimalField(max_digits=10, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2)
    cancelled_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number} - {self.status} ({self.total_amount} THB)"


class OrderItem(models.Model):
    """
    ตารางรายการอาหารในคำสั่งซื้อ (Order Item Detail Table)
    เก็บ Snapshot ข้อมูล ชื่อเมนู, ราคาต่อหน่วย, และตัวเลือกเสริม ณ เวลาสั่งซื้อ
    เพื่อป้องกันผลกระทบเมื่อร้านค้าแก้ไขชื่อหรือราคาเมนูในภายหลัง
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.RESTRICT, related_name='order_items')
    item_name = models.CharField(max_length=255)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.IntegerField()
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    selected_options = models.JSONField(default=list)

    class Meta:
        db_table = 'order_items'

    def __str__(self):
        return f"{self.item_name} x {self.quantity} ({self.total_price} THB)"
