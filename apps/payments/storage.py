import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage

DEFAULT_SLIP_STORAGE_LOCATION = 'private_media'
LEGACY_MEDIA_MARKERS = ('/media/', 'media/')


class SlipPrivateStorage(FileSystemStorage):
    """
    Storage สำหรับไฟล์สลิป (P0-05/P0-11)

    - เก็บนอก MEDIA_ROOT และไม่มี public URL (`base_url=None`) → เข้าถึงได้เฉพาะ signed endpoint
    - อ่าน `settings.SLIP_STORAGE_LOCATION` แบบ dynamic เพื่อให้ override ใน test/สภาพแวดล้อมอื่นได้
    """

    def __init__(self):
        super().__init__(location=None, base_url=None)

    @property
    def base_location(self):
        configured = getattr(settings, 'SLIP_STORAGE_LOCATION', '')
        return configured or os.path.join(settings.BASE_DIR, DEFAULT_SLIP_STORAGE_LOCATION)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


slip_storage = SlipPrivateStorage()


def media_url_to_storage_name(url: str) -> str:
    """แปลง URL/relative path ของ media กลับเป็นชื่อไฟล์ภายใน storage"""
    name = (url or '').strip()
    if not name:
        return ''
    for marker in LEGACY_MEDIA_MARKERS:
        if marker in name:
            name = name.split(marker, 1)[1]
            break
    return name.lstrip('/')


def resolve_slip_file(value: str):
    """
    คืน `(storage, name)` ของไฟล์สลิป

    - ค่าใหม่: เก็บเป็น relative name ใน `slip_storage` (เช่น `payment-slips/<order>/<file>.png`)
    - ค่าเก่า: เก็บเป็น `/media/payment-slips/...` ใต้ `default_storage` (MEDIA_ROOT)
    """
    raw = (value or '').strip()
    if not raw:
        return slip_storage, ''
    if raw.startswith(LEGACY_MEDIA_MARKERS) or '/media/' in raw:
        return default_storage, media_url_to_storage_name(raw)
    return slip_storage, raw.lstrip('/')
