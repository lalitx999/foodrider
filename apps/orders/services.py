import math
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from apps.merchants.models import Merchant, MenuItem, MenuOption
from apps.orders.models import Order, OrderItem, OrderStatus, OrderStatusLog

MONEY_PLACES = Decimal('0.01')

# Transition matrix (BR-5) — ทุกจุดที่เปลี่ยนสถานะออเดอร์ต้องผ่าน transition_order()
ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING_PAYMENT: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY_FOR_PICKUP, OrderStatus.CANCELLED},
    OrderStatus.READY_FOR_PICKUP: {OrderStatus.DELIVERING, OrderStatus.CANCELLED},
    OrderStatus.DELIVERING: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


class OrderCalculationError(Exception):
    """Custom Exception สำหรับความผิดพลาดในการคำนวณราคายอดสั่งซื้อ"""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class InvalidTransition(Exception):
    """เกิดเมื่อพยายามเปลี่ยนสถานะออเดอร์นอก transition matrix (BR-5)"""

    code = 'INVALID_STATUS_TRANSITION'


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)



def validate_delivery_coordinates(lat, lng):
    """ตรวจพิกัดจุดส่ง — คืน (Decimal lat, Decimal lng) หรือ raise INVALID_COORDINATES"""
    if lat is None or lng is None:
        raise OrderCalculationError('พิกัดจุดส่งไม่ถูกต้อง', code='INVALID_COORDINATES')
    try:
        lat_dec = Decimal(str(lat))
        lng_dec = Decimal(str(lng))
    except Exception:
        raise OrderCalculationError('พิกัดจุดส่งไม่ถูกต้อง', code='INVALID_COORDINATES')
    if not (Decimal('-90') <= lat_dec <= Decimal('90')) or not (Decimal('-180') <= lng_dec <= Decimal('180')):
        raise OrderCalculationError('พิกัดจุดส่งไม่ถูกต้อง', code='INVALID_COORDINATES')
    return lat_dec, lng_dec


def compute_delivery_fee(distance_km) -> dict:
    """
    Single source of truth ของค่าจัดส่ง (BR-7)
    คืน {'extra_km', 'delivery_fee', 'rider_fee', 'platform_delivery_fee', 'breakdown', ...}
    ห้ามคำนวณสูตรนี้ซ้ำที่อื่น
    """
    distance = _money(distance_km)
    if distance < Decimal('0.10'):
        distance = Decimal('0.10')

    base_fare = _money(settings.DELIVERY_BASE_FARE)
    base_distance_km = _money(settings.DELIVERY_BASE_DISTANCE_KM)
    per_km_fare = _money(settings.DELIVERY_PER_KM_FARE)
    rider_base = _money(settings.RIDER_BASE_EARNING)
    rider_per_km = _money(settings.RIDER_PER_KM_EARNING)

    extra_km = max(0, math.ceil(distance - base_distance_km))
    delivery_fee = _money(base_fare + per_km_fare * extra_km)
    rider_fee = _money(rider_base + rider_per_km * extra_km)
    platform_delivery_fee = _money(delivery_fee - rider_fee)

    platform_base = _money(base_fare - rider_base)
    platform_per_km = _money(per_km_fare - rider_per_km)

    if delivery_fee != rider_fee + platform_delivery_fee:
        raise OrderCalculationError('สูตรค่าจัดส่งไม่สอดคล้องกัน (delivery_fee != rider + platform)')
    if platform_delivery_fee != platform_base + platform_per_km * extra_km:
        raise OrderCalculationError('สูตรส่วนแบ่งค่าจัดส่งไม่สอดคล้องกัน')

    return {
        'distance_km': distance,
        'extra_km': int(extra_km),
        'delivery_fee': delivery_fee,
        'rider_fee': rider_fee,
        'platform_delivery_fee': platform_delivery_fee,
        'breakdown': {
            'base_fare': str(base_fare),
            'base_distance_km': str(base_distance_km),
            'per_km_fare': str(per_km_fare),
            'extra_km': int(extra_km),
            'rider_base': str(rider_base),
            'rider_per_km': str(rider_per_km),
            'platform_base': str(platform_base),
            'platform_per_km': str(platform_per_km),
        },
    }


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

    lat_dec, lng_dec = validate_delivery_coordinates(delivery_lat, delivery_lng)

    # 1. คำนวณระยะทางจากร้านค้าถึงจุดจัดส่งด้วย PostGIS
    merchant_location = Point(float(merchant.longitude), float(merchant.latitude), srid=4326)
    delivery_location = Point(float(lng_dec), float(lat_dec), srid=4326)

    # คำนวณระยะทางเป็นกิโลเมตร
    distance_meters = merchant_location.distance(delivery_location) * 111319.5  # Approximate meters for SRID 4326
    distance_km = _money(distance_meters / 1000.0)
    if distance_km < Decimal('0.10'):
        distance_km = Decimal('0.10')

    if distance_km > Decimal(str(settings.MAX_DELIVERY_DISTANCE_KM)):
        raise OrderCalculationError(
            f'ระยะทางส่งเกิน {settings.MAX_DELIVERY_DISTANCE_KM:g} กม. ไม่สามารถให้บริการได้',
            code='DELIVERY_TOO_FAR',
        )

    # 2. คำนวณค่าจัดส่ง/ส่วนแบ่งไรเดอร์/กำไรค่าส่ง ด้วยสูตรเดียว (BR-7)
    fee = compute_delivery_fee(distance_km)
    delivery_fee = fee['delivery_fee']

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

    subtotal = _money(subtotal)
    total_amount = _money(subtotal + delivery_fee)
    gp_rate = merchant.gp_rate
    if gp_rate < 0 or gp_rate > 100:
        raise OrderCalculationError('อัตรา GP ของร้านค้าไม่ถูกต้อง')
    platform_fee = _money(subtotal * (gp_rate / Decimal('100.00')))

    return {
        'merchant_id': str(merchant.id),
        'merchant_name': merchant.name,
        'subtotal': subtotal,
        'delivery_fee': delivery_fee,
        'total_amount': total_amount,
        'delivery_distance_km': distance_km,
        'delivery_latitude': lat_dec,
        'delivery_longitude': lng_dec,
        'delivery_location': delivery_location,
        'extra_km': fee['extra_km'],
        'rider_delivery_fee': fee['rider_fee'],
        'platform_delivery_fee': fee['platform_delivery_fee'],
        'platform_fee': platform_fee,
        'delivery_fee_breakdown': fee['breakdown'],
        'items': validated_items,
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
            platform_fee=quote_data['platform_fee'],
            platform_delivery_fee=quote_data['platform_delivery_fee'],
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


def transition_order(order: Order, to_status: str, *, actor=None, role: str = 'SYSTEM', note: str = None) -> Order:
    """
    จุดเดียวที่อนุญาตให้เปลี่ยนสถานะออเดอร์ + เขียน OrderStatusLog (BR-5)
    raise InvalidTransition เมื่อการเปลี่ยนสถานะไม่อยู่ใน transition matrix
    """
    if to_status not in OrderStatus.values:
        raise InvalidTransition(f'สถานะปลายทางไม่ถูกต้อง: {to_status}')

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        from_status = locked.status

        if to_status == from_status:
            raise InvalidTransition(f'ออเดอร์อยู่ในสถานะ {from_status} อยู่แล้ว')
        if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
            raise InvalidTransition(f'ไม่สามารถเปลี่ยนสถานะจาก {from_status} เป็น {to_status}')

        now = timezone.now()
        locked.status = to_status
        update_fields = ['status', 'updated_at']

        if to_status == OrderStatus.PAID and locked.paid_at is None:
            locked.paid_at = now
            update_fields.append('paid_at')
        if to_status == OrderStatus.COMPLETED and locked.completed_at is None:
            locked.completed_at = now
            update_fields.append('completed_at')
        if to_status == OrderStatus.CANCELLED:
            locked.cancelled_by = actor if getattr(actor, 'is_authenticated', False) else None
            update_fields.append('cancelled_by')
            if note:
                locked.cancelled_reason = note
                update_fields.append('cancelled_reason')

        locked.save(update_fields=update_fields)

        OrderStatusLog.objects.create(
            order=locked,
            from_status=from_status,
            to_status=to_status,
            actor=actor if getattr(actor, 'is_authenticated', False) else None,
            role=role,
            note=note,
        )

    order.status = locked.status
    order.paid_at = locked.paid_at
    order.completed_at = locked.completed_at
    order.cancelled_by_id = locked.cancelled_by_id
    order.cancelled_reason = locked.cancelled_reason
    order.updated_at = locked.updated_at
    return order
