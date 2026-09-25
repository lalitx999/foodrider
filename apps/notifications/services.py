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


def reply_line_message(reply_token: str, text: str) -> bool:
    """
    ตอบกลับข้อความใน LINE Chat ผ่าน Messaging API Reply Endpoint
    """
    access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not access_token or not reply_token:
        return False

    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {access_token}"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def reply_line_flex_message(reply_token: str, flex_contents: dict, alt_text: str = 'Food Delivery Notification') -> bool:
    """
    ตอบกลับ Flex Message ใน LINE Chat ผ่าน Messaging API Reply Endpoint
    """
    access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not access_token or not reply_token:
        return False

    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {access_token}"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "flex",
                "altText": alt_text,
                "contents": flex_contents
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def get_liff_target_url(target_path: str) -> str:
    """
    คืนค่า LIFF URL ที่ตรงกับ role destination โดยเฉพาะ
    """
    role_path = next((path for path in ('/customer', '/merchant', '/rider') if target_path.startswith(path)), None)
    liff_id_environment = {'/customer': 'LINE_LIFF_ID_CUSTOMER', '/merchant': 'LINE_LIFF_ID_MERCHANT', '/rider': 'LINE_LIFF_ID_RIDER'}.get(role_path)
    liff_id = os.environ.get(liff_id_environment, '').strip() if liff_id_environment else ''
    base_vercel = os.environ.get('VERCEL_APP_URL', 'https://foodrider.vercel.app')
    if liff_id:
        suffix = target_path.removeprefix(role_path).lstrip('/') if role_path else ''
        return f"https://liff.line.me/{liff_id}/{suffix}" if suffix else f"https://liff.line.me/{liff_id}"
    return f"{base_vercel}{target_path}"


def build_role_selection_flex() -> dict:
    buttons = [('ลงทะเบียนลูกค้า', 'CUSTOMER', '#689D4B'), ('ยื่นเปิดร้านอาหาร', 'MERCHANT', '#689D4B'), ('สมัครเป็นไรเดอร์', 'RIDER', '#2563EB')]
    return {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': [{'type': 'text', 'text': 'ยินดีต้อนรับ', 'weight': 'bold', 'size': 'xl'}, {'type': 'text', 'text': 'เลือกบทบาทเพื่อเริ่มลงทะเบียน', 'wrap': True, 'margin': 'md'}]}, 'footer': {'type': 'box', 'layout': 'vertical', 'spacing': 'sm', 'contents': [{'type': 'button', 'style': 'primary', 'color': color, 'action': {'type': 'postback', 'label': label, 'data': f'onboarding_role={role}'}} for label, role, color in buttons]}}


def build_onboarding_start_flex(role: str) -> dict:
    options = {'CUSTOMER': ('ลงทะเบียนลูกค้า', '/customer/register', '#689D4B'), 'MERCHANT': ('ยื่นเปิดร้านอาหาร', '/merchant/apply', '#689D4B'), 'RIDER': ('สมัครเป็นไรเดอร์', '/rider/apply', '#2563EB')}
    title, path, color = options[role]
    return {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': [{'type': 'text', 'text': title, 'weight': 'bold', 'size': 'lg'}, {'type': 'text', 'text': 'เปิดแบบฟอร์มเพื่อกรอกข้อมูลและส่งคำขอ', 'wrap': True, 'size': 'sm', 'margin': 'md'}]}, 'footer': {'type': 'box', 'layout': 'vertical', 'contents': [{'type': 'button', 'style': 'primary', 'color': color, 'action': {'type': 'uri', 'label': 'เปิดแบบฟอร์ม', 'uri': get_liff_target_url(path)}}]}}


def build_role_entry_flex(role: str) -> dict:
    options = {
        'CUSTOMER': ('เข้าสู่ระบบลูกค้า', '/customer', '#689D4B'),
        'MERCHANT': ('เข้าสู่ระบบร้านค้า', '/merchant', '#689D4B'),
        'RIDER': ('เข้าสู่ระบบไรเดอร์', '/rider', '#2563EB'),
    }
    label, path, color = options[role]
    return {'type': 'bubble', 'body': {'type': 'box', 'layout': 'vertical', 'contents': [{'type': 'text', 'text': 'ยินดีต้อนรับกลับมา', 'weight': 'bold', 'size': 'lg'}, {'type': 'text', 'text': 'เปิดระบบตามสิทธิ์ของคุณ', 'size': 'sm', 'margin': 'md'}]}, 'footer': {'type': 'box', 'layout': 'vertical', 'contents': [{'type': 'button', 'style': 'primary', 'color': color, 'action': {'type': 'uri', 'label': label, 'uri': get_liff_target_url(path)}}]}}


def build_customer_command_flex() -> dict:
    """
    คำสั่ง 'สั่งอาหาร': ตอบกลับการ์ดสั่งซื้อสินค้าพัทยา
    """
    target_url = get_liff_target_url('/customer/register')
    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://images.unsplash.com/photo-1504674900247-0877df9cc836?w=700",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "สั่งอาหารออนไลน์",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1A1A1A"
                },
                {
                    "type": "text",
                    "text": "ค้นหาร้านอร่อยในพื้นที่พัทยา ชลบุรี สั่งง่ายผ่านพิกัด GPS ความแม่นยำสูง",
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True,
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "ลงทะเบียนเพื่อสั่งอาหาร",
                        "uri": target_url
                    },
                    "style": "primary",
                    "color": "#06C755"
                }
            ]
        }
    }


def build_merchant_command_flex(action_type: str = 'OPEN') -> dict:
    """
    คำสั่ง 'เปิดร้าน' / 'ปิดร้าน': ตอบกลับการ์ดจัดการห้องครัว KDS
    """
    target_url = get_liff_target_url('/merchant/apply')
    status_title = "เปิดร้านรับออเดอร์" if action_type == 'OPEN' else "ปิดร้านชั่วคราว"
    status_desc = "ระบบเตรียมพร้อมรับออเดอร์ใหม่เข้าห้องครัว KDS" if action_type == 'OPEN' else "อัปเดตสถานะร้านเป็นปิดรับออเดอร์เรียบร้อย"

    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=700",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": status_title,
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1A1A1A"
                },
                {
                    "type": "text",
                    "text": f"{status_desc} กดปุ่มเพื่อเปิดหน้าจอห้องครัว KDS และจัดการสต๊อก",
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True,
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "ยื่นเปิดร้านอาหาร",
                        "uri": target_url
                    },
                    "style": "primary",
                    "color": "#689D4B"
                }
            ]
        }
    }


def build_rider_command_flex(action_type: str = 'OPEN') -> dict:
    """
    คำสั่ง 'เปิดงาน' / 'ปิดงาน': ตอบกลับการ์ดไรเดอร์ PWA
    """
    target_url = get_liff_target_url('/rider/apply')
    status_title = "เปิดงานสแตนด์บายรับออเดอร์" if action_type == 'OPEN' else "พักงานชั่วคราว"
    status_desc = "ระบบไรเดอร์ออนไลน์ พร้อมรับสัญญาณงานเด้งในพื้นที่พัทยา" if action_type == 'OPEN' else "อัปเดตสถานะไรเดอร์เป็นพักงานเรียบร้อย"

    return {
        "type": "bubble",
        "hero": {
            "type": "image",
            "url": "https://images.unsplash.com/photo-1558981806-ec527fa84c39?w=700",
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": status_title,
                    "weight": "bold",
                    "size": "lg",
                    "color": "#1A1A1A"
                },
                {
                    "type": "text",
                    "text": f"{status_desc} กดปุ่มเพื่อเข้าใช้งานแอปไรเดอร์ ถ่ายรูป POD & เซ็นชื่อ",
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True,
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "สมัครเป็นไรเดอร์",
                        "uri": target_url
                    },
                    "style": "primary",
                    "color": "#2563EB"
                }
            ]
        }
    }


def build_welcome_menu_flex() -> dict:
    """
    เมนูต้อนรับหลัก แสดงตัวเลือก 3 บทบาท (สั่งอาหาร / ห้องครัวร้านค้า / ไรเดอร์)
    """
    customer_url = get_liff_target_url('/customer')
    merchant_url = get_liff_target_url('/merchant')
    rider_url = get_liff_target_url('/rider')

    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "backgroundColor": "#06C755",
            "contents": [
                {
                    "type": "text",
                    "text": "Local Food Delivery Ecosystem",
                    "color": "#FFFFFF",
                    "weight": "bold",
                    "size": "sm"
                },
                {
                    "type": "text",
                    "text": "เลือกเมนูการใช้งานตามบทบาท",
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
                    "text": "ยินดีต้อนรับ! คุณสามารถพิมพ์คำสั่งในแชตเพื่อเปิดระบบได้ทันที:",
                    "size": "xs",
                    "color": "#666666",
                    "wrap": True
                },
                {
                    "type": "text",
                    "text": "• พิมพ์ 'สั่งอาหาร' เพื่อสั่งซื้อสินค้า\n• พิมพ์ 'เปิดร้าน' / 'ปิดร้าน' เพื่อทำอาหาร KDS\n• พิมพ์ 'เปิดงาน' / 'ปิดงาน' เพื่อรับงานไรเดอร์",
                    "size": "xs",
                    "color": "#333333",
                    "weight": "bold",
                    "margin": "md"
                }
            ]
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "สั่งอาหารออนไลน์",
                        "uri": customer_url
                    },
                    "style": "primary",
                    "color": "#06C755"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "ห้องครัวร้านค้า KDS",
                        "uri": merchant_url
                    },
                    "style": "primary",
                    "color": "#689D4B"
                },
                {
                    "type": "button",
                    "action": {
                        "type": "uri",
                        "label": "แอปจัดส่งสำหรับไรเดอร์",
                        "uri": rider_url
                    },
                    "style": "primary",
                    "color": "#2563EB"
                }
            ]
        }
    }


def send_fcm_push_notification(user, title: str, body: str, data_payload: dict = None) -> int:
    """
    ส่ง Web Push Notification ผ่าน FCM ไปยัง PWA ของผู้ใช้ตาม FCM Tokens ที่บันทึกไว้
    """
    tokens = DeviceToken.objects.filter(user=user).values_list('fcm_token', flat=True)
    if not tokens:
        return 0

    # Delivery is intentionally disabled until a real FCM provider is configured.
    return 0
