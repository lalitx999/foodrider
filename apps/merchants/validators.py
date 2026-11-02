from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

ALLOWED_IMAGE_CONTENT_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG', 'WEBP'}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def validate_uploaded_image(file):
    """ตรวจรูปที่อัปโหลด: ขนาด ≤5MB, ชนิด JPG/PNG/WEBP และตรวจ magic bytes จริง (กันไฟล์ปลอม content-type)"""
    if file.size > MAX_IMAGE_BYTES:
        raise serializers.ValidationError('รูปต้องมีขนาดไม่เกิน 5MB')
    if getattr(file, 'content_type', '') not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise serializers.ValidationError('รองรับเฉพาะรูป JPG, PNG หรือ WEBP')
    try:
        file.seek(0)
        with Image.open(file) as image:
            image_format = image.format
            image.verify()
        file.seek(0)
    except (UnidentifiedImageError, OSError, ValueError):
        raise serializers.ValidationError('ไฟล์ที่อัปโหลดไม่ใช่รูปภาพที่ถูกต้อง')
    if image_format not in ALLOWED_IMAGE_FORMATS:
        raise serializers.ValidationError('รองรับเฉพาะรูป JPG, PNG หรือ WEBP')
    return file
