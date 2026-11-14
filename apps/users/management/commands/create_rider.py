from django.core.management.base import BaseCommand, CommandError

from apps.users.management.commands._staff_command import add_account_arguments, prompt_new_password
from apps.users.staff_accounts import AccountInput, StaffAccountError, create_rider


class Command(BaseCommand):
    """
    สร้างบัญชีไรเดอร์ที่ใช้ได้ทันที (Module 33) — ไม่ต้องส่งเอกสาร/รออนุมัติ

    ตัวอย่าง:
      manage.py create_rider --email rider1@example.com --display-name "ไรเดอร์ 1" \\
        --phone 0898765432 --vehicle-plate "1กข 1234 ชลบุรี"
    """

    help = 'สร้างบัญชีไรเดอร์ — ใช้แทนการสมัครไรเดอร์แบบ marketplace'

    def add_arguments(self, parser):
        add_account_arguments(parser)
        parser.add_argument('--vehicle-plate', required=True, help='ทะเบียนรถ')

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
            profile = create_rider(account, vehicle_plate=options['vehicle_plate'])
        except StaffAccountError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(self.style.SUCCESS(
            f'สร้างไรเดอร์ {profile.user.display_name} แล้ว — ล็อกอินด้วย {profile.user.email}'
        ))
