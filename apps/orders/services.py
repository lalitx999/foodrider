import os
import math
import uuid
from decimal import Decimal
from datetime import datetime
from django.db import transaction
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from apps.merchants.models import Merchant, MenuItem, MenuOption
from apps.orders.models import Order, OrderItem, OrderStatus


class OrderCalculationError(Exception):
    """Custom Exception สำหรับความผิดพลาดในการคำนวณราคายอดสั่งซื้อ"""
    pass


def calculate_order_quote(merchant_id: str, delivery_lat: float, delivery_lng: float, items_data: list) -> dict:
    """
    คำนวณค่าอาหาร ค่าจัดส่ง และยอดสุทธิบน Server จริงเท่านั้น (ไม่เชื่อถือผลรวมราคาจาก Frontend)
    ใช้สูตร Haversine บน PostGIS สำหรับคำนวณระยะทางจัดส่ง
    """
    merchant = Merchant.objects.filter(id=merchant_id).first()
    if not merchant:
        raise OrderCalculationError("ไม่พบร้านค้าที่ระบุ")

    if not merchant.is_open:
        raise OrderCalculationError("ร้านค้านี้ปิดบริการอยู่ ไม่สามารถสั่งซื้อได้")

    # 1. คำนวณระยะทางจากร้านค้าถึงจุดจัดส่งด้วย PostGIS
    merchant_location = Point(float(merchant.longitude), float(merchant.latitude), srid=4326)
    delivery_location = Point(delivery_lng, delivery_lat, srid=4326)
    
    # คำนวณระยะทางเป็นกิโลเมตร
    distance_meters = merchant_location.distance(delivery_location) * 111319.5  # Approximate meters for SRID 4326
    distance_km = Decimal(str(round(distance_meters / 1000.0, 2)))
    if distance_km < Decimal('0.1'):
        distance_km = Decimal('0.1')

    # 2. อ่านค่าอัตราค่าจัดส่งจาก Environment Variables
    base_fare = Decimal(os.environ.get('DELIVERY_BASE_FARE', '20.00'))
    base_distance_km = Decimal(os.environ.get('DELIVERY_BASE_DISTANCE_KM', '2.00'))
    per_km_fare = Decimal(os.environ.get('DELIVERY_PER_KM_FARE', '5.00'))

    if distance_km <= base_distance_km:
        delivery_fee = base_fare
    else:
        extra_km = math.ceil(distance_km - base_distance_km)
        delivery_fee = base_fare + (Decimal(str(extra_km)) * per_km_fare)

    # 3. ดึงราคาปัจจุบันจาก DB คำนวณยอด subtotal
    subtotal = Decimal('0.00')
    validated_items = []

    for item_req in items_data:
        menu_item_id = item_req.get('menu_item_id')
        quantity = int(item_req.get('quantity', 1))
        option_ids = item_req.get('option_ids', [])

        if quantity <= 0:
            continue

        menu_item = MenuItem.objects.filter(id=menu_item_id, merchant=merchant).first()
        if not menu_item:
            raise OrderCalculationError(f"ไม่พบรายการอาหารรหัส {menu_item_id}")

        if not menu_item.is_available:
            raise OrderCalculationError(f"เมนู '{menu_item.name}' สินค้าหมดแล้ว")

        # คำนวณราคาตัวเลือกเสริม
        unit_price = menu_item.price
        options_snapshot = []

        if option_ids:
            options = MenuOption.objects.filter(id__in=option_ids, menu_item=menu_item)
            for opt in options:
                unit_price += opt.extra_price
                options_snapshot.append({
                    'id': str(opt.id),
                    'name': opt.name,
                    'price': str(opt.extra_price)
                })

        item_total = unit_price * Decimal(str(quantity))
        subtotal += item_total

        validated_items.append({
            'menu_item': menu_item,
            'item_name': menu_item.name,
            'unit_price': unit_price,
            'quantity': quantity,
            'total_price': item_total,
            'selected_options': options_snapshot
        })

    if not validated_items:
        raise OrderCalculationError("กรุณาเลือกรายการอาหารอย่างน้อย 1 รายการ")

    total_amount = subtotal + delivery_fee
    gp_rate = merchant.gp_rate
    platform_fee = subtotal * (gp_rate / Decimal('100.00'))
    rider_delivery_fee = delivery_fee * Decimal('0.85')  # ค่าตอบแทนรอบวิ่งไรเดอร์ 85% ของค่าจัดส่ง

    return {
        'merchant_id': str(merchant.id),
        'merchant_name': merchant.name,
        'subtotal': subtotal,
        'delivery_fee': delivery_fee,
        'total_amount': total_amount,
        'delivery_distance_km': distance_km,
        'delivery_latitude': Decimal(str(delivery_lat)),
        'delivery_longitude': Decimal(str(delivery_lng)),
        'delivery_location': delivery_location,
        'rider_delivery_fee': rider_delivery_fee,
        'platform_fee': platform_fee,
        'items': validated_items
    }


def generate_order_number() -> str:
    """สร้างเลขที่ออเดอร์รูปแบบ ORD-YYYYMMDD-XXXXX"""
    now_str = datetime.now().strftime('%Y%m%d')
    random_str = str(uuid.uuid4().hex[:5]).upper()
    return f"ORD-{now_str}-{random_str}"


def create_order_transaction(customer, quote_data: dict, delivery_address: str, note_to_merchant: str = None) -> Order:
    """
    สร้าง Order และ OrderItems แบบ Atomic Transaction พร้อม Snapshot ข้อมูลรายการอาหาร
    """
    merchant = Merchant.objects.get(id=quote_data['merchant_id'])

    with transaction.atomic():
        order = Order.objects.create(
            order_number=generate_order_number(),
            customer=customer,
            merchant=merchant,
            status=OrderStatus.PENDING_PAYMENT,
            subtotal=quote_data['subtotal'],
            delivery_fee=quote_data['delivery_fee'],
            total_amount=quote_data['total_amount'],
            delivery_address=delivery_address,
            delivery_latitude=quote_data['delivery_latitude'],
            delivery_longitude=quote_data['delivery_longitude'],
            delivery_location=quote_data['delivery_location'],
            delivery_distance_km=quote_data['delivery_distance_km'],
            note_to_merchant=note_to_merchant,
            rider_delivery_fee=quote_data['rider_delivery_fee'],
            platform_fee=quote_data['platform_fee']
        )

        for item in quote_data['items']:
            OrderItem.objects.create(
                order=order,
                menu_item=item['menu_item'],
                item_name=item['item_name'],
                unit_price=item['unit_price'],
                quantity=item['quantity'],
                total_price=item['total_price'],
                selected_options=item['selected_options']
            )

    return order
