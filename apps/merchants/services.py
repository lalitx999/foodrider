from decimal import Decimal
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.measure import D
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


def get_nearby_open_merchants(lat: float, lng: float, radius_km: float = 10.0):
    """
    ดึงรายการร้านค้าจริงจากฐานข้อมูลตามพิกัด (lat, lng) ของลูกค้า:
    1. ซิงค์โปรไฟล์ร้านค้าจากใบสมัครที่อนุมัติแล้ว (ถ้ายังไม่มีในตาราง merchants)
    2. ซิงค์ PointField location ให้ร้านค้าจริงทุกร้านในฐานข้อมูล
    3. คำนวณระยะทางจริงจากพิกัดลูกค้าด้วย PostGIS Distance
    4. ค้นหาร้านค้าจริงในรัศมี radius_km (เริ่มต้น 10 กม.)
    5. หากนอกรัศมี 10 กม. ให้ขยายไปดึงร้านค้าจริงทั้งหมดในฐานข้อมูลเรียงตามระยะทางที่ใกล้ที่สุด
    """
    user_location = Point(lng, lat, srid=4326)

    # 1. ตรวจสอบใบสมัครที่อนุมัติแล้วแต่ยังไม่มีข้อมูลในตาราง merchants ให้สร้างข้อมูลร้านค้าจริงทันที
    try:
        from apps.users.models import MerchantApplication, ApplicationStatus
        approved_apps = MerchantApplication.objects.filter(status=ApplicationStatus.APPROVED).select_related('user')
        for app in approved_apps:
            if not Merchant.objects.filter(user=app.user).exists():
                app_lat = app.latitude if app.latitude is not None else Decimal('12.9276')
                app_lng = app.longitude if app.longitude is not None else Decimal('100.8771')
                img_url = ''
                if app.storefront_image:
                    try:
                        img_url = app.storefront_image.url
                    except Exception:
                        img_url = ''
                Merchant.objects.create(
                    user=app.user,
                    name=app.store_name or 'ร้านค้าของฉัน',
                    image_url=img_url,
                    phone_number=app.phone_number or '',
                    address=app.address or '',
                    latitude=app_lat,
                    longitude=app_lng,
                    location=Point(float(app_lng), float(app_lat), srid=4326),
                    is_open=True,
                    bank_account_name=app.bank_account_name or 'บัญชีร้านค้า',
                    bank_account_number=app.bank_account_number or '0000000000',
                    bank_name=app.bank_name or 'พร้อมเพย์',
                )
    except Exception:
        pass

    # 2. ตรวจสอบและเติม PointField location ให้ร้านค้าจริงในฐานข้อมูลที่ยังไม่มี
    unlocated = Merchant.objects.filter(location__isnull=True, latitude__isnull=False, longitude__isnull=False)
    for m in unlocated:
        m.location = Point(float(m.longitude), float(m.latitude), srid=4326)
        m.save(update_fields=['location'])

    # 3. ดึงข้อมูลจริงจากตาราง merchants พร้อมคำนวณระยะทางจากพิกัดลูกค้า
    base_qs = Merchant.objects.exclude(location__isnull=True).annotate(
        distance=Distance('location', user_location)
    )

    # กรองร้านค้าที่อยู่ในรัศมี 10 กม. (เรียงจากร้านที่เปิด และใกล้ที่สุด)
    within_radius = base_qs.filter(distance__lte=D(km=radius_km)).order_by('-is_open', 'distance')

    if within_radius.exists():
        selected = list(within_radius)
    else:
        # หากในรัศมี 10 กม. ไม่มีร้าน ให้ดึงร้านค้าจริงทั้งหมดในฐานข้อมูลเรียงตามระยะทางที่ใกล้ที่สุด
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
