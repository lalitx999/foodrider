import uuid
from django.db import models
from apps.orders.models import Order


class SlipTransaction(models.Model):
    """
    ตารางบันทึกการตรวจสอบสลิปการโอนเงิน (Anti-Fraud Slip Transaction Table)
    เก็บประวัติการตรวจสอบและรหัสอ้างอิงธุรกรรมธนาคาร (trans_ref) เพื่อป้องกันการส่งสลิปซ้ำ (Double Spending)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='slip_transactions')
    trans_ref = models.CharField(max_length=100, unique=True, db_index=True)
    sending_bank = models.CharField(max_length=20, null=True, blank=True)
    receiving_bank = models.CharField(max_length=20, null=True, blank=True)
    sender_name = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    slip_image_url = models.TextField()
    is_verified = models.BooleanField(default=False)
    raw_payload = models.JSONField(default=dict)
    verified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slip_transactions'
        ordering = ['-verified_at']

    def __str__(self):
        return f"Slip {self.trans_ref} - Verified: {self.is_verified} ({self.amount} THB)"
