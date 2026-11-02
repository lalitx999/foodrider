"""
เสิร์ฟไฟล์ media เฉพาะโฟลเดอร์ที่เป็นข้อมูลสาธารณะ (P0-11 ทาง A)

- PUBLIC_MEDIA_PREFIXES (ใน settings) = โฟลเดอร์ที่ทุกคนเห็นได้ เช่น รูปเมนู รูปหน้าร้าน
- โฟลเดอร์อื่นใต้ MEDIA_ROOT (เอกสารผู้สมัคร, รูปส่งของ, สลิปเก่า) ไม่ถูกเสิร์ฟ
- production: nginx เสิร์ฟเองตาม location ใน nginx.conf (ต้องตรงกับรายการนี้)
- DEBUG: Django เสิร์ฟผ่าน public_media_urlpatterns()
"""
import re

from django.conf import settings
from django.urls import re_path
from django.views.static import serve


def build_public_media_regex(prefixes):
    """สร้าง regex ที่ match เฉพาะ path ใต้ prefix ที่อนุญาต และกัน '..' (path traversal)"""
    escaped = '|'.join(re.escape(prefix.strip('/')) for prefix in prefixes)
    media_url = settings.MEDIA_URL.lstrip('/')
    return rf'^{re.escape(media_url)}(?P<path>(?:{escaped})/(?!.*\.\.).+)$'


def public_media_urlpatterns():
    prefixes = getattr(settings, 'PUBLIC_MEDIA_PREFIXES', ())
    if not prefixes:
        return []
    return [
        re_path(
            build_public_media_regex(prefixes),
            serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
