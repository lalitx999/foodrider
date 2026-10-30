import uuid
from django.db import models
from apps.orders.models import Order
from apps.users.models import User


class SlipStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    SUPERSEDED = 'SUPERSEDED', 'Superseded'


class SlipTransaction(models.Model):
    """
    ตารางบันทึกการตรวจสอบสลิปการโอนเงิน (Anti-Fraud Slip Transaction Table)
    เก็บประวัติการตรวจสอบและรหัสอ้างอิงธุรกรรมธนาคาร (trans_ref) เพื่อป้องกันการส่งสลิปซ้ำ (Double Spending)

    สถานะการตรวจ (P0-02): PENDING → APPROVED / REJECTED (หรือ SUPERSEDED เมื่อลูกค้าอัปโหลดใหม่)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.RESTRICT, related_name='slip_transactions')
    trans_ref = models.CharField(max_length=100, unique=True, db_index=True)
    sending_bank = models.CharField(max_length=20, null=True, blank=True)
    receiving_bank = models.CharField(max_length=20, null=True, blank=True)
    sender_name = models.CharField(max_length=255, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    slip_image_url = models.TextField(help_text='relative path เช่น /media/payment-slips/... (ห้ามเก็บ absolute URL)')
    is_verified = models.BooleanField(default=False, help_text='derived flag: True เฉพาะสถานะ APPROVED')
    status = models.CharField(max_length=20, choices=SlipStatus.choices, default=SlipStatus.PENDING, db_index=True)
    attempt_no = models.PositiveIntegerField(default=1)
    reviewer = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_slips'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'slip_transactions'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['order'],
                condition=models.Q(status='PENDING'),
                name='uniq_pending_slip_per_order',
            ),
        ]

    def __str__(self):
        return f"Slip {self.trans_ref} - {self.status} ({self.amount} THB)"
