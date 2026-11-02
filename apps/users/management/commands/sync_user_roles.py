from django.core.management.base import BaseCommand
from django.db import transaction

from apps.users.models import (
    ApplicationStatus, CustomerProfile, MerchantApplication, RiderApplication, User, UserRole,
)
from apps.users.services import RoleChangeApprovalError, ensure_merchant_profile, ensure_rider_profile

# เปลี่ยน role ให้อัตโนมัติเฉพาะคนที่ยังไม่มีบทบาทงาน (อัปเกรดจากลูกค้า/ยังไม่เลือก)
ROLES_SAFE_TO_UPGRADE = {UserRole.UNASSIGNED, UserRole.CUSTOMER}


class Command(BaseCommand):
    """
    ซ่อมข้อมูลเก่าครั้งเดียว (P0-08): ผู้ใช้ที่ใบสมัครอนุมัติแล้วแต่ role/profile ไม่ตรงกัน

    เดิม permission เป็นคนสร้าง profile/เปลี่ยน role ให้ทุกครั้งที่เรียก API
    ตอนนี้ permission ตรวจอย่างเดียว จึงต้องรันคำสั่งนี้หลัง deploy เพื่อเติมข้อมูลที่ขาด
    รันซ้ำได้ ไม่สร้างข้อมูลซ้ำ (idempotent) · ใช้ --dry-run เพื่อดูก่อนว่าจะแก้อะไร
    """

    help = 'เติม role/profile ให้ผู้ใช้ที่ใบสมัครอนุมัติแล้ว (รันซ้ำได้)'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='แสดงรายการที่จะแก้ แต่ไม่บันทึก')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        fixed = 0

        with transaction.atomic():
            for application in MerchantApplication.objects.filter(
                status=ApplicationStatus.APPROVED
            ).select_related('user'):
                fixed += self._sync(application.user, UserRole.MERCHANT, 'merchant_profile',
                                    lambda u, app=application: ensure_merchant_profile(u, app), dry_run)

            for application in RiderApplication.objects.filter(
                status=ApplicationStatus.APPROVED
            ).select_related('user'):
                fixed += self._sync(application.user, UserRole.RIDER, 'rider_profile',
                                    lambda u, app=application: ensure_rider_profile(u, app), dry_run)

            for user in User.objects.filter(role=UserRole.CUSTOMER, customer_profile__isnull=True):
                fixed += self._sync(user, UserRole.CUSTOMER, 'customer_profile',
                                    lambda u: CustomerProfile.objects.get_or_create(
                                        user=u, defaults={'default_delivery_address': 'ที่อยู่เริ่มต้น'}),
                                    dry_run)

            if dry_run:
                transaction.set_rollback(True)

        label = 'จะแก้' if dry_run else 'แก้แล้ว'
        self.stdout.write(self.style.SUCCESS(f'{label} {fixed} บัญชี'))

    def _sync(self, user, role, profile_attr, create_profile, dry_run):
        """คืน 1 ถ้ามีการแก้ผู้ใช้คนนี้ ไม่งั้นคืน 0"""
        if user.role == UserRole.ADMIN:
            return 0  # ห้ามลดสิทธิ์แอดมิน

        needs_profile = not hasattr(user, profile_attr)
        needs_role = user.role != role
        if not (needs_profile or needs_role):
            return 0

        changes = []
        if needs_profile:
            try:
                create_profile(user)
            except RoleChangeApprovalError as error:
                # เช่น ใบสมัครร้านไม่มีพิกัด — ข้ามคนนี้ ไม่เปลี่ยน role ให้ ตรวจเอง
                self.stdout.write(self.style.WARNING(f'! {user.email or user.id}: {error}'))
                return 0
            changes.append(f'สร้าง {profile_attr}')
        if needs_role and user.role not in ROLES_SAFE_TO_UPGRADE:
            # เช่น เคยเป็นไรเดอร์แล้วย้ายมาเป็นร้าน → ใบสมัครอนุมัติทั้งคู่ ห้ามเดาว่าควรเป็นอะไร
            self.stdout.write(self.style.WARNING(
                f'! {user.email or user.id}: role ปัจจุบัน {user.role} แต่มีใบสมัคร {role} อนุมัติแล้ว — ไม่แก้ role ให้ ตรวจเอง'
            ))
            needs_role = False
        if needs_role:
            changes.append(f'role {user.role} → {role}')
            user.role = role
            user.save(update_fields=['role', 'updated_at'])

        self.stdout.write(f'- {user.email or user.id}: {", ".join(changes)}' + (' (dry-run)' if dry_run else ''))
        return 1
