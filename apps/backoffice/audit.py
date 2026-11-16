"""
เขียนบันทึกการกระทำของแอดมิน (B1)

เรียก `record_admin_action(...)` หลังการแก้ไขสำเร็จทุกครั้ง — ภายใน transaction เดียวกันถ้ามี
เพื่อให้ "แก้สำเร็จ = มีบันทึก" เสมอ
"""
import logging
from decimal import Decimal

from apps.backoffice.models import AdminAuditLog

logger = logging.getLogger(__name__)

# คำอธิบายภาษาไทยของแต่ละ action (หน้าเว็บใช้แสดง)
ACTION_LABELS = {
    'slip.approve': 'อนุมัติสลิป',
    'slip.reject': 'ปฏิเสธสลิป',
    'branch.create': 'เพิ่มสาขา',
    'branch.activate': 'เปิดการใช้งานสาขา',
    'branch.deactivate': 'ปิดการใช้งานสาขา',
    'branch.password_reset': 'ตั้งรหัสผ่านสาขาใหม่',
    'rider.create': 'เพิ่มไรเดอร์',
    'rider.activate': 'เปิดการใช้งานไรเดอร์',
    'rider.deactivate': 'ปิดการใช้งานไรเดอร์',
    'rider.password_reset': 'ตั้งรหัสผ่านไรเดอร์ใหม่',
    'order.cancel': 'ยกเลิกออเดอร์',
    'order.status': 'เปลี่ยนสถานะออเดอร์',
    'order.assign_rider': 'มอบหมายไรเดอร์',
    'order.reassign_rider': 'เปลี่ยนไรเดอร์',
    'branch.update': 'แก้ข้อมูลสาขา',
    'bank_change.approve': 'อนุมัติเปลี่ยนบัญชีรับเงิน',
    'bank_change.reject': 'ปฏิเสธเปลี่ยนบัญชีรับเงิน',
    'category.create': 'เพิ่มหมวดหมู่เมนู',
    'category.update': 'แก้หมวดหมู่เมนู',
    'category.delete': 'ลบหมวดหมู่เมนู',
    'menu.create': 'เพิ่มเมนู',
    'menu.update': 'แก้เมนู',
    'menu.toggle': 'เปิด/ปิดขายเมนู',
    'menu.hide': 'ซ่อนเมนู',
    'menu.delete': 'ลบเมนู',
    'user.update': 'แก้ข้อมูลผู้ใช้',
    'user.activate': 'เปิดการใช้งานผู้ใช้',
    'user.deactivate': 'ปิดการใช้งานผู้ใช้',
    'user.role': 'เปลี่ยนสิทธิ์ผู้ใช้',
    'user.password_reset': 'ตั้งรหัสผ่านผู้ใช้ใหม่',
    'device_token.deactivate': 'ปิดอุปกรณ์รับแจ้งเตือน',
}


def _plain(value):
    """แปลงค่าให้เก็บเป็น JSON ได้"""
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def diff(before: dict, after: dict) -> dict:
    """{"field": {"from": x, "to": y}} เฉพาะช่องที่ค่าเปลี่ยน"""
    return {
        key: {'from': _plain(before.get(key)), 'to': _plain(after.get(key))}
        for key in after
        if _plain(before.get(key)) != _plain(after.get(key))
    }


def _client_ip(request) -> str:
    if request is None:
        return ''
    meta = getattr(request, 'META', {})
    # nginx ตั้ง X-Real-IP จาก IP ที่ Caddy เห็น (deploy/nginx.conf)
    return (meta.get('HTTP_X_REAL_IP') or meta.get('REMOTE_ADDR') or '')[:64]


def record_admin_action(
    actor,
    action: str,
    *,
    target_type: str,
    target_id,
    target_label: str = '',
    changes: dict | None = None,
    note: str = '',
    request=None,
) -> AdminAuditLog:
    actor_label = ''
    if actor is not None and getattr(actor, 'is_authenticated', False):
        actor_label = f'{actor.display_name} <{actor.email}>'[:255]
    else:
        actor = None
    entry = AdminAuditLog.objects.create(
        actor=actor,
        actor_label=actor_label,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        target_label=(target_label or '')[:255],
        changes=changes or {},
        note=note or '',
        ip_address=_client_ip(request),
    )
    logger.info('admin-audit %s %s %s:%s', actor_label, action, target_type, target_id)
    return entry


def serialize_audit_log(entry: AdminAuditLog) -> dict:
    return {
        'id': str(entry.id),
        'action': entry.action,
        'action_label': ACTION_LABELS.get(entry.action, entry.action),
        'actor': entry.actor_label,
        'target_type': entry.target_type,
        'target_id': entry.target_id,
        'target_label': entry.target_label,
        'changes': entry.changes,
        'note': entry.note,
        'ip_address': entry.ip_address,
        'created_at': entry.created_at,
    }
