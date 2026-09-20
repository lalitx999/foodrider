from decimal import Decimal
from django.db import transaction
from apps.orders.models import Order, OrderStatus
from apps.riders.models import RiderProfile
from apps.users.models import User


class JobClaimError(Exception):
    """Custom Exception เมื่อเกิดข้อผิดพลาดในการกดรับงานเดลิเวอรี"""
    pass


def claim_rider_job_atomic(rider_user: User, order_id: str) -> Order:
    """
    อัลกอริทึมการกดรับงานแข่งกัน (Race Condition Control):
    ใช้ Pessimistic Locking (select_for_update) บน Database Transaction 
    เพื่อป้องกันไม่ให้ไรเดอร์ 2 คนสามารถกดรับงานเดียวกันได้พร้อมกัน (First-come, First-served)
    """
    with transaction.atomic():
        # select_for_update() จะทำการล็อกแถวข้อมูลออเดอร์ในระดับ Database row
        target_order = Order.objects.select_for_update().filter(id=order_id).first()

        if not target_order:
            raise JobClaimError("ไม่พบงานเดลิเวอรีที่ระบุ")

        if target_order.status != OrderStatus.READY_FOR_PICKUP or target_order.rider is not None:
            raise JobClaimError("งานนี้มีไรเดอร์ท่านอื่นกดรับไปแล้ว (JOB_ALREADY_CLAIMED)")

        target_order.rider = rider_user
        target_order.status = OrderStatus.DELIVERING
        target_order.save()

    return target_order


def complete_rider_job_atomic(rider_user: User, order_id: str, proof_image_url: str) -> Order:
    """
    ปิดงานจัดส่งอาหารสำเร็จ:
    เปลี่ยนสถานะเป็น COMPLETED และบวกเพิ่มค่าตอบแทนรอบวิ่งเข้า rider_profiles.wallet_balance แบบ Atomic
    """
    rider_profile = RiderProfile.objects.filter(user=rider_user).first()
    if not rider_profile:
        raise JobClaimError("ไม่พบโปรไฟล์ไรเดอร์สำหรับผู้ใช้นี้")

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(id=order_id, rider=rider_user).first()

        if not order:
            raise JobClaimError("ไม่พบงานเดลิเวอรีของคุณ")

        if order.status != OrderStatus.DELIVERING:
            raise JobClaimError("งานนี้ไม่ได้อยู่ในสถานะกำลังจัดส่ง")

        order.status = OrderStatus.COMPLETED
        order.save()

        # คำนวณเพิ่มค่ารอบเข้ากระเป๋าเงินไรเดอร์
        rider_profile.wallet_balance += order.rider_delivery_fee
        rider_profile.save()

    return order
