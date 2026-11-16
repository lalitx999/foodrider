"""
แอดมินจัดการออเดอร์ (Module 32 เฟส B · B2)

ทุกการเปลี่ยนสถานะยังผ่าน `transition_order` (BR-5) — แอดมินไม่ได้ข้ามกติกาเดิม
และทุกการกระทำเขียน AdminAuditLog ใน transaction เดียวกัน
ยอดเงินในออเดอร์แก้ไม่ได้จากหลังบ้าน (ดูอย่างเดียว)
"""
import logging

from django.db import transaction

from apps.backoffice.audit import record_admin_action
from apps.notifications.fcm import create_and_send_notification
from apps.orders.models import Order, OrderStatus, OrderStatusLog
from apps.orders.services import InvalidTransition, transition_order
from apps.riders.models import RiderProfile
from apps.users.models import UserRole

logger = logging.getLogger(__name__)

MIN_REASON_CHARS = 5

# แอดมินเลื่อนสถานะไปข้างหน้าได้ทีละขั้นเท่านั้น
# - ยืนยันชำระเงิน → ใช้คิวตรวจสลิป (มีหลักฐาน)  - รับงานส่ง → ใช้ "มอบหมายไรเดอร์"
ADMIN_NEXT_STATUS = {
    OrderStatus.PAID: OrderStatus.PREPARING,
    OrderStatus.PREPARING: OrderStatus.READY_FOR_PICKUP,
    OrderStatus.DELIVERING: OrderStatus.COMPLETED,
}
CLOSED_STATUSES = {OrderStatus.COMPLETED, OrderStatus.CANCELLED}
PAID_STATUSES = {OrderStatus.PAID, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP, OrderStatus.DELIVERING}

STATUS_LABELS = {
    OrderStatus.PENDING_PAYMENT: 'รอชำระเงิน',
    OrderStatus.PAID: 'ชำระแล้ว',
    OrderStatus.PREPARING: 'กำลังทำอาหาร',
    OrderStatus.READY_FOR_PICKUP: 'รอไรเดอร์รับ',
    OrderStatus.DELIVERING: 'กำลังจัดส่ง',
    OrderStatus.COMPLETED: 'ส่งสำเร็จ',
    OrderStatus.CANCELLED: 'ยกเลิก',
}


class AdminOrderError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _notify_later(user, title: str, body: str, order: Order) -> None:
    if user is None:
        return

    def send():
        try:
            create_and_send_notification(
                user=user, title=title, body=body,
                data={'type': 'ORDER_UPDATED', 'order_id': str(order.id), 'status': order.status},
            )
        except Exception:  # แจ้งเตือนล้มเหลวต้องไม่ทำให้การแก้ออเดอร์ล้มเหลว
            logger.exception('Cannot notify user %s about order %s', user.pk, order.pk)

    transaction.on_commit(send)


def _require_reason(reason: str, field_label: str) -> str:
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON_CHARS:
        raise AdminOrderError('REASON_REQUIRED', f'กรุณาระบุ{field_label} (อย่างน้อย {MIN_REASON_CHARS} ตัวอักษร)')
    return reason


def allowed_actions(order: Order) -> dict:
    """ปุ่มที่หน้าเว็บควรแสดงสำหรับออเดอร์นี้"""
    next_status = ADMIN_NEXT_STATUS.get(order.status)
    if next_status == OrderStatus.COMPLETED and not order.rider_id:
        next_status = None
    return {
        'can_cancel': order.status not in CLOSED_STATUSES,
        'next_status': next_status,
        'next_status_label': STATUS_LABELS.get(next_status) if next_status else None,
        'can_assign_rider': order.status == OrderStatus.READY_FOR_PICKUP and not order.rider_id,
        'can_reassign_rider': order.status == OrderStatus.DELIVERING and bool(order.rider_id),
        'refund_needed_if_cancelled': order.status in PAID_STATUSES,
    }


def admin_cancel_order(order_id, actor, reason: str, *, request=None) -> tuple[Order, bool]:
    """ยกเลิกออเดอร์ — คืน (order, ต้องคืนเงินลูกค้าเองหรือไม่)"""
    reason = _require_reason(reason, 'เหตุผลที่ยกเลิก')
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).select_related('customer', 'merchant__user', 'rider').filter(pk=order_id).first()
        if order is None:
            raise AdminOrderError('ORDER_NOT_FOUND', 'ไม่พบออเดอร์นี้')
        if order.status in CLOSED_STATUSES:
            raise AdminOrderError('ORDER_CLOSED', f'ออเดอร์นี้{STATUS_LABELS[order.status]}แล้ว ยกเลิกไม่ได้')
        from_status = order.status
        refund_needed = from_status in PAID_STATUSES
        try:
            transition_order(order, OrderStatus.CANCELLED, actor=actor, role='ADMIN', note=f'แอดมินยกเลิก: {reason}')
        except InvalidTransition as error:
            raise AdminOrderError('INVALID_STATUS_TRANSITION', str(error)) from error

        record_admin_action(
            actor, 'order.cancel', target_type='order', target_id=order.pk, target_label=order.order_number,
            changes={'status': {'from': from_status, 'to': OrderStatus.CANCELLED}},
            note=reason + (' · ต้องคืนเงินลูกค้า' if refund_needed else ''), request=request,
        )
        body = f'ออเดอร์ {order.order_number} ถูกยกเลิก: {reason}'
        _notify_later(order.customer, 'ออเดอร์ถูกยกเลิก', body + (' — ร้านจะติดต่อคืนเงิน' if refund_needed else ''), order)
        _notify_later(order.merchant.user, 'ออเดอร์ถูกยกเลิก', body, order)
        _notify_later(order.rider, 'งานถูกยกเลิก', body, order)
    return order, refund_needed


def admin_advance_status(order_id, actor, to_status: str, note: str = '', *, request=None) -> Order:
    """เลื่อนสถานะไปขั้นถัดไป (เช่น จอครัวค้าง แอดมินกดแทน)"""
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).select_related('customer', 'merchant__user', 'rider').filter(pk=order_id).first()
        if order is None:
            raise AdminOrderError('ORDER_NOT_FOUND', 'ไม่พบออเดอร์นี้')
        expected = ADMIN_NEXT_STATUS.get(order.status)
        if expected is None or to_status != expected:
            raise AdminOrderError(
                'INVALID_STATUS_TRANSITION',
                f'จากสถานะ "{STATUS_LABELS.get(order.status, order.status)}" แอดมินเปลี่ยนเป็น "{STATUS_LABELS.get(to_status, to_status)}" ไม่ได้',
            )
        if to_status == OrderStatus.COMPLETED:
            if not order.rider_id:
                raise AdminOrderError('RIDER_REQUIRED', 'ออเดอร์นี้ยังไม่มีไรเดอร์')
            note = _require_reason(note, 'เหตุผลที่ปิดงานแทนไรเดอร์')
        from_status = order.status
        try:
            transition_order(order, to_status, actor=actor, role='ADMIN', note=f'แอดมินเปลี่ยนสถานะ{": " + note if note else ""}')
        except InvalidTransition as error:
            raise AdminOrderError('INVALID_STATUS_TRANSITION', str(error)) from error

        changes = {'status': {'from': from_status, 'to': to_status}}
        if to_status == OrderStatus.COMPLETED:
            # ปิดงานแทนไรเดอร์ = ไรเดอร์ได้ค่ารอบเหมือนปิดงานเอง (ไม่ให้ไรเดอร์เสียรายได้)
            profile = RiderProfile.objects.select_for_update().filter(user_id=order.rider_id).first()
            if profile:
                before = profile.wallet_balance
                profile.wallet_balance += order.rider_delivery_fee
                profile.save(update_fields=['wallet_balance', 'updated_at'])
                changes['rider_wallet'] = {'from': str(before), 'to': str(profile.wallet_balance)}

        record_admin_action(
            actor, 'order.status', target_type='order', target_id=order.pk, target_label=order.order_number,
            changes=changes, note=note, request=request,
        )
        label = STATUS_LABELS.get(to_status, to_status)
        _notify_later(order.customer, 'อัปเดตออเดอร์', f'ออเดอร์ {order.order_number}: {label}', order)
        if to_status == OrderStatus.READY_FOR_PICKUP:
            for rider_profile in RiderProfile.objects.select_related('user').filter(is_online=True, user__is_active=True):
                _notify_later(rider_profile.user, 'มีงานใหม่', f'ออเดอร์ {order.order_number} พร้อมให้รับ', order)
    return order


def admin_assign_rider(order_id, actor, rider_profile_id, note: str = '', *, request=None) -> Order:
    """มอบหมายไรเดอร์ (รอไรเดอร์รับ → กำลังจัดส่ง) หรือเปลี่ยนไรเดอร์ระหว่างจัดส่ง"""
    with transaction.atomic():
        order = Order.objects.select_for_update(of=('self',)).select_related('customer', 'rider').filter(pk=order_id).first()
        if order is None:
            raise AdminOrderError('ORDER_NOT_FOUND', 'ไม่พบออเดอร์นี้')
        profile = RiderProfile.objects.select_related('user').filter(pk=rider_profile_id).first()
        if profile is None or profile.user.role != UserRole.RIDER:
            raise AdminOrderError('RIDER_NOT_FOUND', 'ไม่พบไรเดอร์คนนี้')
        if not profile.user.is_active:
            raise AdminOrderError('RIDER_INACTIVE', 'ไรเดอร์คนนี้ถูกปิดการใช้งาน')
        new_rider = profile.user
        old_rider = order.rider

        if order.status == OrderStatus.READY_FOR_PICKUP and order.rider_id is None:
            order.rider = new_rider
            order.save(update_fields=['rider', 'updated_at'])
            try:
                transition_order(order, OrderStatus.DELIVERING, actor=actor, role='ADMIN',
                                 note=f'แอดมินมอบหมายงานให้ {new_rider.display_name}')
            except InvalidTransition as error:
                raise AdminOrderError('INVALID_STATUS_TRANSITION', str(error)) from error
            action = 'order.assign_rider'
            changes = {'rider': {'from': None, 'to': new_rider.display_name},
                       'status': {'from': OrderStatus.READY_FOR_PICKUP, 'to': OrderStatus.DELIVERING}}
        elif order.status == OrderStatus.DELIVERING and order.rider_id:
            if order.rider_id == new_rider.pk:
                raise AdminOrderError('SAME_RIDER', 'ไรเดอร์คนนี้รับงานนี้อยู่แล้ว')
            note = _require_reason(note, 'เหตุผลที่เปลี่ยนไรเดอร์')
            order.rider = new_rider
            order.save(update_fields=['rider', 'updated_at'])
            # สถานะไม่เปลี่ยน แต่บันทึกในประวัติออเดอร์ให้เห็นว่าเปลี่ยนคนส่ง
            OrderStatusLog.objects.create(
                order=order, from_status=OrderStatus.DELIVERING, to_status=OrderStatus.DELIVERING,
                actor=actor, role='ADMIN', note=f'เปลี่ยนไรเดอร์ {old_rider.display_name} → {new_rider.display_name}: {note}',
            )
            action = 'order.reassign_rider'
            changes = {'rider': {'from': old_rider.display_name, 'to': new_rider.display_name}}
            _notify_later(old_rider, 'งานถูกย้าย', f'ออเดอร์ {order.order_number} ถูกย้ายให้ไรเดอร์คนอื่น', order)
        else:
            raise AdminOrderError('CANNOT_ASSIGN', 'มอบหมายไรเดอร์ได้เฉพาะออเดอร์ที่ "รอไรเดอร์รับ" หรือ "กำลังจัดส่ง"')

        record_admin_action(
            actor, action, target_type='order', target_id=order.pk, target_label=order.order_number,
            changes=changes, note=note, request=request,
        )
        _notify_later(new_rider, 'ได้รับมอบหมายงาน', f'ออเดอร์ {order.order_number} — เปิดแอปเพื่อดูรายละเอียด', order)
        _notify_later(order.customer, 'ไรเดอร์กำลังไปส่ง', f'{new_rider.display_name} รับออเดอร์ {order.order_number} แล้ว', order)
    return order
