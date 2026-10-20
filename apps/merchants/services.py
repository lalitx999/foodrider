from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


def get_nearby_open_merchants(lat: float, lng: float, radius_km: float = 10.0):
    """
    ดึงรายการร้านค้าที่อยู่ใกล้พิกัด (lat, lng)
    1. ค้นหาร้านค้าที่เปิดอยู่ (is_open=True) ภายในรัศมี radius_km (เริ่มต้น 10 กม.)
    2. หากในรัศมีไม่มีร้านค้า (หรือมีน้อยมาก) ขยายการค้นหาร้านที่ใกล้ที่สุดเพิ่มเติมอัตโนมัติ
    3. คำนวณระยะทางจริง (distance_km) ด้วยสูตร PostGIS Haversine
    """
    user_location = Point(lng, lat, srid=4326)

    # ตรวจสอบและเติม PointField location ให้ร้านค้าที่ยังไม่มี
    unlocated = Merchant.objects.filter(location__isnull=True, latitude__isnull=False, longitude__isnull=False)
    for m in unlocated:
        m.location = Point(float(m.longitude), float(m.latitude), srid=4326)
        m.save(update_fields=['location'])

    base_qs = Merchant.objects.exclude(location__isnull=True).annotate(
        distance=Distance('location', user_location)
    )

    # 1. ค้นหาร้านที่เปิดอยู่ภายในรัศมี 10 กม.
    within_radius = base_qs.filter(is_open=True, distance__lte=D(km=radius_km)).order_by('distance')

    if within_radius.exists():
        selected = list(within_radius)
    else:
        # 2. ขยายการค้นหาร้านที่เปิดอยู่ทั้งหมดโดยเรียงตามระยะทางที่ใกล้ที่สุด
        all_open = base_qs.filter(is_open=True).order_by('distance')
        if all_open.exists():
            selected = list(all_open)
        else:
            # 3. หากยังไม่มีร้านเปิดบริการเลย ให้ดึงร้านค้าที่มีในระบบเรียงตามระยะทาง เพื่อไม่ให้หน้าจอว่างเปล่า
            selected = list(base_qs.order_by('-is_open', 'distance'))

    # แนบฟิลด์ distance_km สำหรับ Serializer
    result = []
    for merchant in selected:
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
