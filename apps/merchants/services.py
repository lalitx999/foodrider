from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


def get_nearby_open_merchants(lat: float, lng: float):
    """
    ดึงรายการร้านค้าที่เปิดอยู่ (is_open = True)
    คำนวณระยะทางจากพิกัด (lat, lng) ด้วยสูตร Haversine บน PostGIS
    และเรียงลำดับจากร้านที่ใกล้ที่สุด
    """
    user_location = Point(lng, lat, srid=4326)
    
    merchants = Merchant.objects.filter(is_open=True).annotate(
        distance=Distance('location', user_location)
    ).order_by('distance')

    # แนบฟิลด์ distance_km สำหรับ Serializer
    result = []
    for merchant in merchants:
        # distance object คืนค่าเป็น Distance(m=...)
        dist_km = round(merchant.distance.m / 1000.0, 2) if merchant.distance else 0.0
        merchant.distance_km = dist_km
        result.append(merchant)

    return result


def get_merchant_full_menu(merchant_id: str):
    """
    ดึงโครงสร้าง หมวดหมู่ -> รายการอาหาร -> ตัวเลือกเสริม สำหรับฝั่งลูกค้า
    """
    categories = Category.objects.filter(merchant_id=merchant_id).prefetch_related(
        'items', 'items__options'
    ).order_by('sort_order', 'name')
    
    return categories
