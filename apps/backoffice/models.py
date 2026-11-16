import uuid

from django.db import models

from apps.users.models import User


class AdminAuditLog(models.Model):
    """
    บันทึกทุกการกระทำของแอดมินในหลังบ้าน (Module 32 เฟส B · B1)

    - เขียนอย่างเดียว ไม่มีหน้าแก้/ลบ (หลักฐานย้อนหลัง)
    - เก็บชื่อ/อีเมลผู้ทำแบบ snapshot ไว้ด้วย เผื่อบัญชีถูกปิดภายหลัง
    - `changes` = {"field": {"from": ค่าเดิม, "to": ค่าใหม่}} — ห้ามเก็บรหัสผ่าน/ข้อมูลลับ
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_audit_logs')
    actor_label = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=32, db_index=True)
    target_id = models.CharField(max_length=64, db_index=True)
    target_label = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    ip_address = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'admin_audit_logs'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['target_type', 'target_id', '-created_at'], name='audit_target_idx')]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.actor_label} {self.action} {self.target_type}:{self.target_id}'
