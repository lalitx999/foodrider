from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from apps.users.models import User, UserRole
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption

SAMPLE_MERCHANTS = [
    {
        "name": "ส้มตำป้าบุญ พัทยาใต้",
        "phone": "0897771122",
        "address": "พัทยาใต้ ซอย 15 บางละมุง ชลบุรี",
        "lat": 12.9150,
        "lng": 100.8750,
        "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "เมนูยำ & ส้มตำ",
                "items": [
                    {"name": "ยำแซลมอนไข่แดงเค็ม", "price": 250.00, "desc": "แซลมอนสดคลุกน้ำยำรสแซ่บ", "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=500"},
                    {"name": "ส้มตำปูปลาร้าแซ่บเว่อร์", "price": 80.00, "desc": "ปลาร้าต้มสุกหอมนัว โรยเม็ดกระถิน", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500"},
                    {"name": "คอหมูย่างเตาถ่าน", "price": 120.00, "desc": "หมูคัดพิเศษ หมักซอสสมุนไพรย่างไฟอ่อน", "image_url": "https://images.unsplash.com/photo-1562967914-608f82629710?w=500"}
                ]
            }
        ]
    },
    {
        "name": "เรือนไทย ซีฟู้ด พัทยาใต้",
        "phone": "038425911",
        "address": "พัทยาใต้ สาย 2 เมืองพัทยา",
        "lat": 12.9248,
        "lng": 100.8710,
        "image_url": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "เมนูกุ้งเผา & ทะเล",
                "items": [
                    {"name": "กุ้งแม่น้ำเผา (500 กรัม)", "price": 490.00, "desc": "มันเยิ้ม เสิร์ฟพร้อมน้ำจิ้มซีฟู้ดมะนาวสด", "image_url": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=500"},
                    {"name": "หอยเชลล์ย่างเนยกระเทียม", "price": 280.00, "desc": "หอยเชลล์ตัวใหญ่เนยแท้ หอมฟุ้ง", "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500"}
                ]
            }
        ]
    },
    {
        "name": "ปูเพ็ญ ซีฟู้ด หาดจอมเทียน",
        "phone": "038231725",
        "address": "ริมหาดจอมเทียน พัทยาใต้",
        "lat": 12.8885,
        "lng": 100.8708,
        "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "ซีฟู้ดหาดจอมเทียน",
                "items": [
                    {"name": "ปูนึ่งนมสดหาดจอมเทียน", "price": 550.00, "desc": "ปูม้าสดเป็นๆ แกะเนื้อพร้อมทาน", "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500"},
                    {"name": "หมึกไข่นึ่งมะนาว", "price": 320.00, "desc": "หมึกไข่แน่นเต็มตัว รสจัดจ้าน", "image_url": "https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?w=500"}
                ]
            }
        ]
    },
    {
        "name": "แม่ศรีนวล พัทยากลาง",
        "phone": "038444333",
        "address": "พัทยากลาง ซอย 12",
        "lat": 12.9335,
        "lng": 100.8850,
        "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "แกงไทยโบราณ",
                "items": [
                    {"name": "แกงส้มชะอมกุ้งสด", "price": 220.00, "desc": "เครื่องแกงตำมือ รสชาติเข้มข้นจัดจ้าน", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500"},
                    {"name": "ต้มข่าไก่บ้านใบมะขามอ่อน", "price": 180.00, "desc": "กะทิคั้นสด หอมละมุนสมุนไพร", "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=500"}
                ]
            }
        ]
    },
    {
        "name": "ป้าติ๋ม ส้มตำพัทยากลาง",
        "phone": "0876665544",
        "address": "พัทยากลาง สาย 3",
        "lat": 12.9320,
        "lng": 100.8810,
        "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "ส้มตำ & ไก่ย่าง",
                "items": [
                    {"name": "ส้มตำไทยไข่เค็ม", "price": 70.00, "desc": "ถั่วคั่วเอง มะนาวสด รสชาติกลมกล่อม", "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=500"},
                    {"name": "ไก่ย่างวิเชียรบุรี (ครึ่งตัว)", "price": 120.00, "desc": "หนังกรอบ เนื้อนุ่ม น้ำจิ้มแจ่วมะขาม", "image_url": "https://images.unsplash.com/photo-1562967914-608f82629710?w=500"},
                    {"name": "ลาบหมูคั่วข้าวคั่วหอม", "price": 90.00, "desc": "หมูสับนุ่ม คลุกข้าวคั่วหอมกรุ่น", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500"}
                ]
            }
        ]
    },
    {
        "name": "ข้าวผัดปู เซ็นทรัลพัทยา",
        "phone": "0819998877",
        "address": "ถนนพัทยากลาง ตรงข้ามเซ็นทรัล",
        "lat": 12.9360,
        "lng": 100.8840,
        "image_url": "https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "ข้าวผัด & อาหารจานเดียว",
                "items": [
                    {"name": "ข้าวผัดปูเนื้อก้อนพิเศษ", "price": 150.00, "desc": "หอมกลิ่นกระทะ ข้าวเรียงเม็ดสวย เนื้อปูเน้นๆ", "image_url": "https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=500"},
                    {"name": "กะเพราปูราดข้าวไข่ดาวกรอบ", "price": 160.00, "desc": "พริกแห้งใบกะเพราป่า รสร้อนแรง", "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500"}
                ]
            }
        ]
    },
    {
        "name": "ก๋วยเตี๋ยวเรือนายหงอก พัทยากลาง",
        "phone": "0845556677",
        "address": "ถนนพัทยากลาง ซอย 7",
        "lat": 12.9347,
        "lng": 100.8825,
        "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "ก๋วยเตี๋ยวเรือรสเด็ด",
                "items": [
                    {"name": "ก๋วยเตี๋ยวเรือเนื้อวากิว", "price": 129.00, "desc": "เนื้อวากิวสไลด์บาง ซุปน้ำตกเข้มข้นตุ๋นยาจีน", "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=500"},
                    {"name": "กากหมูเจียวโบราณ", "price": 35.00, "desc": "กรุบกรอบ ทอดสดใหม่ทุกเช้า", "image_url": "https://images.unsplash.com/photo-1562967914-608f82629710?w=500"}
                ]
            }
        ]
    },
    {
        "name": "เจ้แอ๊ด ซีฟู้ด นาเกลือ",
        "phone": "0891234567",
        "address": "ตลาดเก่านาเกลือ พัทยาเหนือ",
        "lat": 12.9550,
        "lng": 100.8900,
        "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "เมนูเด็ดเจ้แอ๊ด",
                "items": [
                    {"name": "ปูม่านึ่ง 1 กก.", "price": 650.00, "desc": "ปูม้าสดจากเรือประมงนาเกลือ หวานฉ่ำ", "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500"},
                    {"name": "ปลากะพงนึ่งมะนาว", "price": 390.00, "desc": "ปลากะพงสดเป็น นึ่งมะนาวสวนพริกขี้หนูสวน", "image_url": "https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?w=500"}
                ]
            }
        ]
    },
    {
        "name": "Surf & Turf Beach Club Pattaya",
        "phone": "0917583888",
        "address": "ซอยนาเกลือ 16 พัทยาเหนือ",
        "lat": 12.9515,
        "lng": 100.8872,
        "image_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "เบอร์เกอร์ & สเต๊ก",
                "items": [
                    {"name": "Ribeye Steak Premium", "price": 590.00, "desc": "เนื้อริบอายพรีเมียม กริลล์สุกกำลังดี", "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?w=500"},
                    {"name": "Surf & Turf Wagyu Burger", "price": 289.00, "desc": "เบอร์เกอร์เนื้อวากิวและกุ้งลายเสือ ซอสทรัฟเฟิล", "image_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500"}
                ]
            }
        ]
    },
    {
        "name": "มุมอร่อย พัทยาเหนือ (Moom Aroi)",
        "phone": "038223232",
        "address": "พัทยาเหนือ นาเกลือ ริมทะเล",
        "lat": 12.9580,
        "lng": 100.8920,
        "image_url": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=600&auto=format&fit=crop&q=80",
        "categories": [
            {
                "name": "อาหารทะเลแนะนำ",
                "items": [
                    {"name": "ต้มยำกุ้งแม่น้ำหม้อไฟ", "price": 380.00, "desc": "ต้มยำน้ำข้นกุ้งแม่น้ำตัวโต สมุนไพรแน่น", "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=500"},
                    {"name": "ปลากะพงทอดน้ำปลา", "price": 450.00, "desc": "ทอดกรอบนอกนุ่มใน น้ำปลาเคี่ยวหวานกำลังดี", "image_url": "https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?w=500"}
                ]
            }
        ]
    }
]


def seed_pattaya_merchants():
    """
    Creates or updates the 10 Pattaya restaurants, ensuring is_open=True, valid PointField location,
    categories, and menu items.
    """
    created_count = 0
    for idx, data in enumerate(SAMPLE_MERCHANTS, start=1):
        username = f"merchant_pattaya_{idx}"
        email = f"pattaya_store_{idx}@foodrider.app"

        user, _ = User.objects.get_or_create(
            email=email,
            defaults={
                "display_name": data["name"],
                "role": UserRole.MERCHANT,
                "phone_number": data["phone"],
            }
        )
        if user.role != UserRole.MERCHANT:
            user.role = UserRole.MERCHANT
            user.save(update_fields=["role"])

        lat = Decimal(str(data["lat"]))
        lng = Decimal(str(data["lng"]))
        point = Point(float(lng), float(lat), srid=4326)

        merchant, created = Merchant.objects.get_or_create(
            user=user,
            defaults={
                "name": data["name"],
                "description": data["address"],
                "image_url": data["image_url"],
                "phone_number": data["phone"],
                "address": data["address"],
                "latitude": lat,
                "longitude": lng,
                "location": point,
                "is_open": True,
                "bank_account_name": data["name"],
                "bank_account_number": f"089000{idx:04d}",
                "bank_name": "พร้อมเพย์",
            }
        )

        # Ensure open and location are up to date
        needs_save = False
        if not merchant.is_open:
            merchant.is_open = True
            needs_save = True
        if merchant.location is None:
            merchant.location = point
            merchant.latitude = lat
            merchant.longitude = lng
            needs_save = True
        if not merchant.image_url:
            merchant.image_url = data["image_url"]
            needs_save = True
        if needs_save:
            merchant.save()

        # Seed categories and menu items
        for cat_idx, cat_data in enumerate(data.get("categories", [])):
            category, _ = Category.objects.get_or_create(
                merchant=merchant,
                name=cat_data["name"],
                defaults={"sort_order": cat_idx}
            )
            for item_data in cat_data.get("items", []):
                MenuItem.objects.get_or_create(
                    merchant=merchant,
                    category=category,
                    name=item_data["name"],
                    defaults={
                        "price": Decimal(str(item_data["price"])),
                        "description": item_data.get("desc", ""),
                        "image_url": item_data.get("image_url", ""),
                        "is_available": True,
                    }
                )

        created_count += 1

    return created_count


class Command(BaseCommand):
    help = "Seed 10 Pattaya restaurants with categories and menus, set to is_open=True"

    def handle(self, *args, **options):
        self.stdout.write("Seeding Pattaya merchants...")
        total = seed_pattaya_merchants()
        self.stdout.write(self.style.SUCCESS(f"Successfully seeded/updated {total} merchants."))
