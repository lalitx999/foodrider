import logging

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D

from apps.merchants.models import Merchant, Category, MenuItem, MenuOption

logger = logging.getLogger(__name__)

DEFAULT_RADIUS_KM = 10.0


def get_nearby_open_merchants(lat: float, lng: float, radius_km: float = DEFAULT_RADIUS_KM):
    """
    คืนร้านที่ "เปิดอยู่" และอยู่ในรัศมี `radius_km` เรียงจากใกล้สุด (P0-12)

    - GET ต้องไม่เขียน DB (ห้าม sync/backfill ในนี้) — ถ้าข้อมูลพิกัดไม่ครบ ให้ข้ามร้านนั้น
    - ไม่มี fallback "คืนทั้งประเทศ": นอกรัศมี = list ว่าง
    """
    try:
        user_location = Point(lng, lat, srid=4326)
        queryset = (
            Merchant.objects.filter(is_open=True)
            .exclude(location__isnull=True)
            .annotate(distance=Distance('location', user_location))
            .filter(distance__lte=D(km=radius_km))
            .order_by('distance')
        )

        result = []
        for merchant in queryset:
            merchant.distance_km = round(merchant.distance.m / 1000.0, 2) if merchant.distance else 0.0
            result.append(merchant)
        return result
    except Exception:
        # ห้ามให้ค้นหาร้าล้มทั้งหน้าเพราะข้อมูลพิกัดของร้านใดร้านหนึ่งเสีย
        logger.exception('get_nearby_open_merchants failed (lat=%s, lng=%s, radius=%s)', lat, lng, radius_km)
        return []


def get_merchant_full_menu(merchant_id: str):
    """
    ดึงโครงสร้าง หมวดหมู่ -> รายการอาหาร -> ตัวเลือกเสริม สำหรับฝั่งลูกค้า
    """
    categories = Category.objects.filter(merchant_id=merchant_id).prefetch_related(
        'items', 'items__options'
    ).order_by('sort_order', 'name')
    
    return categories
