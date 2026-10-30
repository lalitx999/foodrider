"""
Helper สำหรับสร้างลิงก์นำทาง Google Maps ฝั่งไรเดอร์ (P0-16)

กติกาสำคัญ: ห้ามคืน 0 แทนพิกัดที่หายไป — ถ้าพิกัดไม่ครบ/ผิดรูป ให้คืน None
เพื่อให้ frontend ซ่อนปุ่มแผนที่ (ไม่เปิด 0,0 หรือ NaN,NaN)
"""

import math

GOOGLE_MAPS_DIR_URL = 'https://www.google.com/maps/dir/?api=1'

# ความเร็วเฉลี่ยของไรเดอร์ (กม./ชม.) ใช้ประมาณเวลาส่ง
AVERAGE_SPEED_KMH = 20
MIN_ESTIMATED_MINUTES = 10


def to_coordinate(value):
    """แปลงค่าเป็น float ที่ใช้ได้ ถ้าไม่ใช่พิกัดจริงให้คืน None"""
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def normalize_coordinate_pair(lat, lng):
    """
    คืน (lat, lng) เป็น float เมื่อเป็นพิกัดที่ใช้ได้จริง ไม่เช่นนั้นคืน None

    ถือว่า (0, 0) คือ "ไม่มีพิกัด" (Null Island) ซึ่งเกิดจากข้อมูลหายบ่อยที่สุด
    """
    lat_value = to_coordinate(lat)
    lng_value = to_coordinate(lng)
    if lat_value is None or lng_value is None:
        return None
    if not (-90 <= lat_value <= 90) or not (-180 <= lng_value <= 180):
        return None
    if lat_value == 0 and lng_value == 0:
        return None
    return lat_value, lng_value


def build_navigation_url(destination_lat, destination_lng, origin_lat=None, origin_lng=None):
    """สร้าง Google Maps Directions URL หรือคืน None ถ้าพิกัดปลายทางใช้ไม่ได้"""
    destination = normalize_coordinate_pair(destination_lat, destination_lng)
    if destination is None:
        return None

    url = f'{GOOGLE_MAPS_DIR_URL}&destination={destination[0]},{destination[1]}&travelmode=driving'
    origin = normalize_coordinate_pair(origin_lat, origin_lng)
    if origin is not None:
        url = f'{GOOGLE_MAPS_DIR_URL}&origin={origin[0]},{origin[1]}&destination={destination[0]},{destination[1]}&travelmode=driving'
    return url


def build_navigation_target(lat, lng, origin_lat=None, origin_lng=None):
    """คืน dict {lat, lng, google_maps_url} โดย lat/lng = None เมื่อพิกัดใช้ไม่ได้"""
    coordinates = normalize_coordinate_pair(lat, lng)
    if coordinates is None:
        return {'lat': None, 'lng': None, 'google_maps_url': None}
    return {
        'lat': coordinates[0],
        'lng': coordinates[1],
        'google_maps_url': build_navigation_url(
            coordinates[0], coordinates[1], origin_lat, origin_lng
        ),
    }


def estimate_delivery_minutes(distance_km):
    """ประมาณเวลาส่งจากระยะทาง (20 กม./ชม.) ปัดขึ้น ขั้นต่ำ 10 นาที"""
    distance = to_coordinate(distance_km)
    if distance is None or distance < 0:
        return None
    minutes = math.ceil(distance / AVERAGE_SPEED_KMH * 60)
    return max(minutes, MIN_ESTIMATED_MINUTES)


def build_order_navigation(order, origin_lat=None, origin_lng=None):
    """สร้าง navigation payload ของออเดอร์ (ไปร้าน + ไปลูกค้า)"""
    merchant = order.merchant
    return {
        'to_store': build_navigation_target(
            merchant.latitude, merchant.longitude, origin_lat, origin_lng
        ),
        'to_customer': build_navigation_target(
            order.delivery_latitude, order.delivery_longitude, origin_lat, origin_lng
        ),
    }
