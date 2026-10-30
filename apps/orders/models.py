import uuid
from decimal import Decimal

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
    platform_delivery_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00')
    )  # กำไรค่าส่งของแพลตฟอร์ม: 5 + 1*extra_km (BR-7)
    cancelled_reason = models.TextField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_orders'
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_number} - {self.status} ({self.total_amount} THB)"

    @property
    def rider_earning(self):
        return self.rider_delivery_fee

    @property
    def platform_total_income(self):
        return self.platform_fee + self.platform_delivery_fee


class OrderStatusLog(models.Model):
    """บันทึกทุกการเปลี่ยนสถานะออเดอร์ เพื่อการตรวจสอบย้อนหลัง (Audit Trail)"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_logs')
    from_status = models.CharField(max_length=30, choices=OrderStatus.choices, null=True, blank=True)
    to_status = models.CharField(max_length=30, choices=OrderStatus.choices, db_index=True)
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='order_status_logs'
    )
    role = models.CharField(max_length=20, blank=True, help_text='SYSTEM / CUSTOMER / MERCHANT / RIDER / ADMIN')
    note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'order_status_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order_id}: {self.from_status} -> {self.to_status} ({self.role})'



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
