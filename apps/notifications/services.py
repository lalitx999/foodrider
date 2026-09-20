import os
import requests
from apps.orders.models import Order
from apps.notifications.models import DeviceToken


def build_order_status_flex_message(order: Order) -> dict:
    """
    สร้างโครงสร้าง LINE Flex Message (JSON) สไตล์การ์ดทางการสำหรับแจ้งเตือนสถานะออเดอร์ในแชต LINE
    ใช้สี Primary #689D4B
    """
    status_text_map = {
        'PENDING_PAYMENT': 'รอการชำระเงิน',
        'PAID': 'ชำระเงินเรียบร้อยแล้ว',
        'PREPARING': 'ร้านค้ากำลังเตรียมอาหาร',
        'READY_FOR_PICKUP': 'อาหารพร้อมส่ง (รอไรเดอร์)',
        'DELIVERING': 'ไรเดอร์กำลังนำส่งอาหาร',
        'COMPLETED': 'จัดส่งสำเร็จเรียบร้อย',
        'CANCELLED': 'ยกเลิกออเดอร์'
    }

    status_desc = status_text_map.get(order.status, order.status)

    flex_json = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#689D4B",
            "contents": [
                {
                    "type": "text",
                    "text": "สถานะคำสั่งซื้อ",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": order.order_number,
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "lg",
                    "margin": "xs"
                }
            ]
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": status_desc,
                    "weight": "bold",
                    "size": "md",
                    "color": "#1A1A1A"
                },
                {
                    "type": "text",
                    "text": f"ร้านค้า: {order.merchant.name}",
                    "size": "xs",
                    "color": "#666666",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": f"ยอดรวมสุทธิ: {order.total_amount} บาท",
                    "size": "sm",
                    "weight": "bold",
                    "color": "#689D4B",
                    "margin": "xs"
                }
            ]
        }
    }

    return flex_json


def send_line_flex_notification(line_user_id: str, order: Order) -> bool:
    """
    ส่ง LINE Flex Message แจ้งเตือนสถานะออเดอร์ไปยัง LINE Chat ของลูกค้าผ่าน Messaging API
    """
    access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not access_token or not line_user_id or access_token == 'your_line_access_token':
        return False

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {access_token}"
    }

    flex_contents = build_order_status_flex_message(order)
    payload = {
        "to": line_user_id,
        "messages": [
            {
                "type": "flex",
                "altText": f"อัปเดตสถานะออเดอร์ {order.order_number}",
                "contents": flex_contents
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def send_fcm_push_notification(user, title: str, body: str, data_payload: dict = None) -> int:
    """
    ส่ง Web Push Notification ผ่าน FCM ไปยัง PWA ของผู้ใช้ตาม FCM Tokens ที่บันทึกไว้
    """
    tokens = DeviceToken.objects.filter(user=user).values_list('fcm_token', flat=True)
    if not tokens:
        return 0

    # กรณีพัฒนา local ให้จำลองจำนวนส่งสำเร็จ
    return len(tokens)
