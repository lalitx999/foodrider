"""
Django system checks ของค่าจัดส่ง (BR-7 / P0-15)

ถ้าตั้ง env ให้ไรเดอร์ได้มากกว่าที่ลูกค้าจ่าย ระบบต้องไม่ start (fail fast)
เพื่อไม่ให้คิดเงินผิดตั้งแต่ออเดอร์แรก
"""

from django.conf import settings
from django.core.checks import Error, register


@register()
def delivery_pricing_checks(app_configs, **kwargs):
    errors = []
    base_fare = settings.DELIVERY_BASE_FARE
    per_km_fare = settings.DELIVERY_PER_KM_FARE
    rider_base = settings.RIDER_BASE_EARNING
    rider_per_km = settings.RIDER_PER_KM_EARNING

    if rider_base > base_fare:
        errors.append(Error(
            'RIDER_BASE_EARNING ต้องไม่มากกว่า DELIVERY_BASE_FARE',
            hint=f'ตอนนี้ RIDER_BASE_EARNING={rider_base} > DELIVERY_BASE_FARE={base_fare}',
            id='orders.E001',
        ))

    if rider_per_km > per_km_fare:
        errors.append(Error(
            'RIDER_PER_KM_EARNING ต้องไม่มากกว่า DELIVERY_PER_KM_FARE',
            hint=f'ตอนนี้ RIDER_PER_KM_EARNING={rider_per_km} > DELIVERY_PER_KM_FARE={per_km_fare}',
            id='orders.E002',
        ))

    if base_fare < 0 or per_km_fare < 0 or rider_base < 0 or rider_per_km < 0:
        errors.append(Error(
            'ค่าจัดส่งและรายได้ไรเดอร์ต้องไม่ติดลบ',
            id='orders.E003',
        ))

    return errors
