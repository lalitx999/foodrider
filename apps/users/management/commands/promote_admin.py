from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User, UserRole


class Command(BaseCommand):
    """
    เลื่อนสิทธิ์ผู้ใช้เป็น ADMIN เพื่อเข้าใช้ backoffice (frontend `/admin`) — P1-10

    จำเป็นเพราะ `IsAdminRole` ตรวจ `role == 'ADMIN'` ไม่ใช่ `is_staff`
    ผู้ใช้ที่สร้างด้วย `createsuperuser` จะมี role = UNASSIGNED จึงเข้า /admin ไม่ได้
    """

    help = 'กำหนดสิทธิ์ ADMIN (role=ADMIN + is_staff) ให้ผู้ใช้ เพื่อเข้าใช้หน้า /admin'

    def add_arguments(self, parser):
        parser.add_argument('identifier', help='อีเมลหรือเบอร์โทรศัพท์ของผู้ใช้')
        parser.add_argument(
            '--revoke',
            action='store_true',
            help='ถอดสิทธิ์ ADMIN (role=UNASSIGNED, is_staff=False)',
        )

    def handle(self, *args, **options):
        identifier = (options['identifier'] or '').strip()
        if not identifier:
            raise CommandError('กรุณาระบุอีเมลหรือเบอร์โทรศัพท์ของผู้ใช้')

        user = User.objects.filter(email__iexact=identifier).first()
        if user is None:
            user = User.objects.filter(phone_number=identifier).first()
        if user is None:
            raise CommandError(f'ไม่พบผู้ใช้ที่ตรงกับ: {identifier}')

        if options['revoke']:
            user.role = UserRole.UNASSIGNED
            user.is_staff = False
            user.save(update_fields=['role', 'is_staff', 'updated_at'])
            self.stdout.write(
                self.style.WARNING(f'ถอดสิทธิ์ ADMIN ของ {user.display_name} ({user.email}) เรียบร้อยแล้ว')
            )
            return

        user.role = UserRole.ADMIN
        user.is_staff = True
        user.is_active = True
        user.save(update_fields=['role', 'is_staff', 'is_active', 'updated_at'])
        self.stdout.write(
            self.style.SUCCESS(
                f'{user.display_name} ({user.email}) เป็นแอดมินแล้ว — เข้าใช้ /admin ได้ทันที'
            )
        )
