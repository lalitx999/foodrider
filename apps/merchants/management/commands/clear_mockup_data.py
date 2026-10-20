from django.core.management.base import BaseCommand
from django.db.models import Q
from apps.users.models import User
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


class Command(BaseCommand):
    help = "ลบข้อมูล Mockup/ข้อมูลจำลองออกจากฐานข้อมูลทั้งหมด และคงไว้เฉพาะข้อมูลจริง"

    def handle(self, *args, **options):
        self.stdout.write("กำลังตรวจสอบและค้นหาข้อมูล Mockup ในระบบ...")

        # ระบุเงื่อนไขค้นหาข้อมูล Mockup / ข้อมูลทดสอบ
        mock_user_q = (
            Q(email__endswith='@foodrider.app') |
            Q(email__endswith='@pattaya.local') |
            Q(email__icontains='pattaya_store_') |
            Q(email__icontains='pa_boon_') |
            Q(email__icontains='ruan_thai_') |
            Q(email__icontains='pu_pen_') |
            Q(email__icontains='mae_srinual_') |
            Q(email__icontains='pa_tim_') |
            Q(email__icontains='crab_fried_') |
            Q(email__icontains='nai_ngok_') |
            Q(email__icontains='jae_add_') |
            Q(email__icontains='surf_turf_') |
            Q(email__icontains='moom_aroi_')
        )

        mock_users = User.objects.filter(mock_user_q)
        mock_user_count = mock_users.count()

        mock_merchants = Merchant.objects.filter(
            Q(user__in=mock_users) |
            Q(name__icontains='ส้มตำป้าบุญ') |
            Q(name__icontains='เรือนไทย ซีฟู้ด') |
            Q(name__icontains='ปูเพ็ญ ซีฟู้ด') |
            Q(name__icontains='แม่ศรีนวล') |
            Q(name__icontains='ป้าติ๋ม ส้มตำ') |
            Q(name__icontains='ข้าวผัดปู เซ็นทรัล') |
            Q(name__icontains='ก๋วยเตี๋ยวเรือนายหงอก') |
            Q(name__icontains='เจ้แอ๊ด ซีฟู้ด') |
            Q(name__icontains='Surf & Turf') |
            Q(name__icontains='มุมอร่อย พัทยาเหนือ')
        )
        mock_merchant_count = mock_merchants.count()

        # ลบเมนูและหมวดหมู่ของร้าน mockup
        mock_categories = Category.objects.filter(merchant__in=mock_merchants)
        mock_menu_items = MenuItem.objects.filter(merchant__in=mock_merchants)
        mock_options = MenuOption.objects.filter(menu_item__in=mock_menu_items)

        options_count = mock_options.count()
        items_count = mock_menu_items.count()
        cats_count = mock_categories.count()

        # ทำการลบ
        mock_options.delete()
        mock_menu_items.delete()
        mock_categories.delete()
        mock_merchants.delete()
        mock_users.delete()

        self.stdout.write(self.style.SUCCESS(
            f"ลบข้อมูล Mockup สำเร็จ:\n"
            f" - ร้านค้า Mockup: {mock_merchant_count} ร้าน\n"
            f" - ผู้ใช้ Mockup: {mock_user_count} คน\n"
            f" - เมนู Mockup: {items_count} เมนู\n"
            f" - หมวดหมู่ Mockup: {cats_count} หมวดหมู่\n"
            f" - ตัวเลือกเสริม: {options_count} รายการ"
        ))

        # ตรวจสอบร้านค้าจริงที่เหลืออยู่ในฐานข้อมูล พร้อมเปิดสถานะร้านจริง (is_open = True)
        remaining_merchants = Merchant.objects.all()
        for m in remaining_merchants:
            if not m.is_open:
                m.is_open = True
                m.save(update_fields=['is_open'])

        self.stdout.write(self.style.NOTICE(
            f"\nร้านค้าจริงที่พร้อมใช้งานในระบบขณะนี้ ({remaining_merchants.count()} ร้าน):"
        ))
        for m in remaining_merchants:
            self.stdout.write(f"  • {m.name} (เจ้าของ: {m.user.email if m.user else '-'}, สถานะ: {'เปิดรับออเดอร์' if m.is_open else 'ปิด'})")
