"""ส่วนกลางของคำสั่ง create_branch / create_rider — รับรหัสผ่านแบบไม่โชว์บนจอ ไม่ผ่าน argument"""
import getpass

from django.core.management.base import CommandError

MAX_PASSWORD_PROMPTS = 3


def add_account_arguments(parser) -> None:
    parser.add_argument('--email', required=True, help='อีเมลที่ใช้เข้าสู่ระบบ')
    parser.add_argument('--display-name', required=True, help='ชื่อที่แสดงในระบบ')
    parser.add_argument('--phone', required=True, help='เบอร์โทร')
    parser.add_argument(
        '--use-existing',
        action='store_true',
        help='ใช้บัญชีที่สมัครไว้แล้ว (บทบาทต้องยังไม่ใช่ร้าน/ไรเดอร์/แอดมิน) — ไม่เปลี่ยนรหัสผ่าน',
    )


def prompt_new_password() -> str:
    """ถามรหัสผ่าน 2 รอบผ่าน getpass — ไม่รับทาง argument เพื่อไม่ให้ค้างใน shell history"""
    for _ in range(MAX_PASSWORD_PROMPTS):
        password = getpass.getpass('ตั้งรหัสผ่าน (อย่างน้อย 12 ตัวอักษร): ')
        confirm = getpass.getpass('ยืนยันรหัสผ่านอีกครั้ง: ')
        if password != confirm:
            print('รหัสผ่านไม่ตรงกัน ลองใหม่')
            continue
        if not password:
            print('รหัสผ่านว่างไม่ได้ ลองใหม่')
            continue
        return password
    raise CommandError('ตั้งรหัสผ่านไม่สำเร็จ')
