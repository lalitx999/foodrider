from django.conf import settings
from django.core import signing

MEDIA_SALT = 'food.private-media'


def make_media_token(obj_id, ttl=None):
    """สร้าง token อายุสั้นสำหรับเข้าถึงไฟล์ส่วนตัว (สลิป/เอกสาร) — P0-05"""
    return signing.dumps({'id': str(obj_id)}, salt=MEDIA_SALT)


def read_media_token(token, max_age=None):
    """ถอด token (raise signing.BadSignature / signing.SignatureExpired)"""
    if max_age is None:
        max_age = getattr(settings, 'SLIP_SIGNED_URL_TTL_SECONDS', 600)
    return signing.loads(token, salt=MEDIA_SALT, max_age=max_age)
