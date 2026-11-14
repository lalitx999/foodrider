from django.core.management.base import BaseCommand, CommandError

from apps.users.management.commands._staff_command import add_account_arguments, prompt_new_password
from apps.users.staff_accounts import AccountInput, StaffAccountError, create_branch


class Command(BaseCommand):
    """
    สร้างสาขาใหม่พร้อมบัญชีจอครัว (Module 33) — 1 สาขา = 1 บัญชีล็อกอิน

    ตัวอย่าง:
      manage.py create_branch --email branch1@example.com --display-name "ครัวสาขา 1" \\
        --phone 0812345678 --name "ร้านตัวอย่าง สาขา 1" --address "..." --lat 12.9236 --lng 100.8825
    """

    help = 'สร้างสาขา (ร้าน) พร้อมบัญชีจอครัว — ใช้แทนการสมัครร้านแบบ marketplace'

    def add_arguments(self, parser):
        add_account_arguments(parser)
        parser.add_argument('--name', required=True, help='ชื่อสาขาที่ลูกค้าเห็น')
        parser.add_argument('--address', required=True, help='ที่อยู่สาขา')
        parser.add_argument('--lat', required=True, help='latitude ของสาขา (พิกัดจริง)')
        parser.add_argument('--lng', required=True, help='longitude ของสาขา (พิกัดจริง)')
        parser.add_argument('--description', default='', help='คำอธิบายร้าน (ไม่บังคับ)')
        parser.add_argument('--bank-name', default='', help='ธนาคาร (ไม่บังคับ — เงินเข้าบัญชีกลาง)')
        parser.add_argument('--bank-account-name', default='', help='ชื่อบัญชี (ไม่บังคับ)')
        parser.add_argument('--bank-account-number', default='', help='เลขบัญชี (ไม่บังคับ)')

    def handle(self, *args, **options):
        password = None if options['use_existing'] else prompt_new_password()
        account = AccountInput(
            email=options['email'],
            display_name=options['display_name'],
            phone_number=options['phone'],
            password=password,
            use_existing=options['use_existing'],
        )
        try:
            branch = create_branch(
                account,
                name=options['name'],
                address=options['address'],
                latitude=options['lat'],
                longitude=options['lng'],
                description=options['description'],
                bank_name=options['bank_name'],
                bank_account_name=options['bank_account_name'],
                bank_account_number=options['bank_account_number'],
            )
        except StaffAccountError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS(
            f'สร้างสาขา "{branch.name}" แล้ว ({branch.latitude}, {branch.longitude}) — '
            f'ล็อกอินจอครัวด้วย {branch.user.email} · สาขายังปิดอยู่ ให้กดเปิดร้านจากจอครัวเมื่อพร้อม'
        ))
