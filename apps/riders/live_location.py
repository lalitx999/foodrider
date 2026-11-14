"""
พิกัดไรเดอร์แบบสด (Module 33 · S-2)

- ไรเดอร์ส่งพิกัดถี่ (~5 วิ) ระหว่างมีงาน → เก็บ "พิกัดล่าสุด" ไว้ใน cache (Redis บน production)
  ไม่เขียนฐานข้อมูลทุกครั้ง เพื่อไม่ให้ DB ทำงานหนักโดยไม่จำเป็น
- เขียนลง `RiderProfile.current_location` ไม่เกิน 1 ครั้ง / DB_SYNC_SECONDS (ใช้หาไรเดอร์ใกล้ร้าน)
- เวลา `updated_at` ใช้เวลาของเซิร์ฟเวอร์เสมอ ไม่เชื่อเวลาจากมือถือ
"""
from dataclasses import dataclass

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.utils import timezone

LOCATION_TTL_SECONDS = 30 * 60   # จำพิกัดล่าสุดไว้ 30 นาที — ลูกค้ายังเห็น "ตำแหน่งล่าสุดเมื่อ x นาทีที่แล้ว"
STALE_AFTER_SECONDS = 120        # เกิน 2 นาทีถือว่าพิกัดเก่า (ไรเดอร์อาจออกจากแอป/สัญญาณหาย)
DB_SYNC_SECONDS = 60
MAX_ACCURACY_METERS = 1000       # แย่กว่านี้ไม่ใช่ GPS ที่ใช้ติดตามได้


class LocationError(Exception):
    def __init__(self, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


@dataclass(frozen=True)
class LiveLocation:
    lat: float
    lng: float
    accuracy: float | None
    heading: float | None
    speed: float | None
    updated_at: str  # ISO-8601 (เวลาเซิร์ฟเวอร์)

    def age_seconds(self, now=None) -> int:
        now = now or timezone.now()
        updated = timezone.datetime.fromisoformat(self.updated_at)
        return max(0, int((now - updated).total_seconds()))

    def as_payload(self, now=None) -> dict:
        age = self.age_seconds(now)
        return {
            'lat': self.lat,
            'lng': self.lng,
            'accuracy': self.accuracy,
            'heading': self.heading,
            'speed': self.speed,
            'updated_at': self.updated_at,
            'age_seconds': age,
            'is_stale': age > STALE_AFTER_SECONDS,
        }


def _cache_key(rider_user_id) -> str:
    return f'rider:live-location:{rider_user_id}'


def _db_sync_key(rider_user_id) -> str:
    return f'rider:live-location:db-sync:{rider_user_id}'


def _optional_number(raw, field: str, *, low: float, high: float) -> float | None:
    if raw is None or raw == '':
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise LocationError('INVALID_LOCATION', f'{field} ต้องเป็นตัวเลข', field)
    if value != value or not (low <= value <= high):  # value != value → NaN
        raise LocationError('INVALID_LOCATION', f'{field} อยู่นอกช่วงที่รับได้', field)
    return value


def parse_location_payload(data) -> dict:
    """ตรวจ payload จากมือถือ — ไม่มีพิกัดสำรอง ไม่รับ 0,0"""
    try:
        lat = float(data.get('lat'))
        lng = float(data.get('lng'))
    except (TypeError, ValueError):
        raise LocationError('INVALID_LOCATION', 'ต้องส่ง lat และ lng เป็นตัวเลข', 'lat')
    if lat != lat or lng != lng or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise LocationError('INVALID_LOCATION', 'พิกัดอยู่นอกช่วง', 'lat')
    if lat == 0 and lng == 0:
        raise LocationError('INVALID_LOCATION', 'พิกัด 0,0 ไม่ใช่ตำแหน่งจริง', 'lat')

    accuracy = _optional_number(data.get('accuracy'), 'accuracy', low=0, high=100_000)
    if accuracy is not None and accuracy > MAX_ACCURACY_METERS:
        raise LocationError('LOW_ACCURACY', f'GPS ยังไม่แม่นพอ (±{int(accuracy)} ม.) ไม่บันทึกตำแหน่งนี้', 'accuracy')

    return {
        'lat': round(lat, 7),
        'lng': round(lng, 7),
        'accuracy': accuracy,
        'heading': _optional_number(data.get('heading'), 'heading', low=0, high=360),
        'speed': _optional_number(data.get('speed'), 'speed', low=0, high=100),  # m/s (~360 กม./ชม.)
    }


def save_live_location(rider_profile, payload: dict) -> LiveLocation:
    location = LiveLocation(updated_at=timezone.now().isoformat(), **payload)
    cache.set(_cache_key(rider_profile.user_id), location.__dict__, LOCATION_TTL_SECONDS)

    # cache.add สำเร็จเฉพาะครั้งแรกในช่วง DB_SYNC_SECONDS → เขียน DB อย่างมากนาทีละครั้ง
    if cache.add(_db_sync_key(rider_profile.user_id), 1, DB_SYNC_SECONDS):
        rider_profile.current_latitude = payload['lat']
        rider_profile.current_longitude = payload['lng']
        rider_profile.current_location = Point(payload['lng'], payload['lat'], srid=4326)
        rider_profile.save(update_fields=['current_latitude', 'current_longitude', 'current_location', 'updated_at'])
    return location


def get_live_location(rider_user_id) -> LiveLocation | None:
    raw = cache.get(_cache_key(rider_user_id))
    if not raw:
        return None
    try:
        return LiveLocation(**raw)
    except TypeError:
        return None


def clear_live_location(rider_user_id) -> None:
    cache.delete(_cache_key(rider_user_id))
