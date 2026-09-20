from django.core.management.base import BaseCommand
from django.contrib.gis.geos import Point
from apps.users.models import User, UserRole
from apps.merchants.models import Merchant, Category, MenuItem, MenuOption


class Command(BaseCommand):
    help = 'Populates PostgreSQL PostGIS database with 10 Pattaya Merchants and full menu catalogs'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding 10 Pattaya Merchants into PostgreSQL..."))

        pattaya_merchants = [
            {
                "username": "moom_aroi_north",
                "display_name": "มุมอร่อย พัทยาเหนือ",
                "name": "มุมอร่อย พัทยาเหนือ (Moom Aroi Seafood)",
                "description": "อาหารทะเลสด ปลากะพงทอดน้ำปลาพรีเมียม วิวทะเลพัทยาเหนือ",
                "phone_number": "038223232",
                "address": "พัทยาเหนือ นาเกลือ",
                "latitude": 12.9580,
                "longitude": 100.8920,
                "image_url": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=500",
                "categories": [
                    {
                        "name": "อาหารทะเลแนะนำ",
                        "items": [
                            {"name": "ปลากะพงทอดน้ำปลา", "price": 450, "description": "ปลากะพงสดทอดกรอบ ราดซอสน้ำปลาเคี่ยวกลมกล่อม", "image_url": "https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?w=500"},
                            {"name": "ต้มยำกุ้งแม่น้ำหม้อไฟ", "price": 380, "description": "ต้มยำกุ้งแม่น้ำตัวใหญ่ น้ำข้นรสจัดจ้าน", "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "surf_turf_pattaya",
                "display_name": "Surf & Turf Pattaya",
                "name": "Surf & Turf Beach Club Pattaya",
                "description": "เบอร์เกอร์วากิว สเต๊กพรีเมียม บีชคลับสุดชิล พัทยาเหนือ",
                "phone_number": "0917583888",
                "address": "ซอยนาเกลือ 16 พัทยาเหนือ",
                "latitude": 12.9515,
                "longitude": 100.8872,
                "image_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500",
                "categories": [
                    {
                        "name": "เบอร์เกอร์ & สเต๊ก",
                        "items": [
                            {"name": "Surf & Turf Wagyu Burger", "price": 289, "description": "เนื้อวากิวบดพรีเมียม พร้อมกุ้งย่างและชีสเยิ้ม", "image_url": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=500"},
                            {"name": "Ribeye Steak Premium", "price": 590, "description": "สเต๊กเนื้อริบอายเกรดพรีเมียม เสิร์ฟพร้อมมันฝรั่งทอด", "image_url": "https://images.unsplash.com/photo-1544025162-d76694265947?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "jae_add_seafood",
                "display_name": "เจ้แอ๊ด ซีฟู้ด",
                "name": "เจ้แอ๊ด ซีฟู้ด นาเกลือ",
                "description": "อาหารทะเลสดจากเรือประมง นาเกลือ พัทยาเหนือ",
                "phone_number": "0891234567",
                "address": "ตลาดเก่านาเกลือ พัทยาเหนือ",
                "latitude": 12.9550,
                "longitude": 100.8900,
                "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500",
                "categories": [
                    {
                        "name": "เมนูเด็ดเจ้แอ๊ด",
                        "items": [
                            {"name": "ปูม่านึ่ง 1 กก.", "price": 650, "description": "ปูม้าสดเนื้อหวาน นึ่งพร้อมน้ำจิ้มซีฟู้ดมะนาวสด", "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "nai_ngok_noodle",
                "display_name": "ก๋วยเตี๋ยวเรือนายหงอก",
                "name": "ก๋วยเตี๋ยวเรือนายหงอก พัทยากลาง",
                "description": "ก๋วยเตี๋ยวเรือสูตรอยุธยา รสเด็ดเข้มข้น พัทยากลาง",
                "phone_number": "0845556677",
                "address": "ถนนพัทยากลาง ซอย 7",
                "latitude": 12.9347,
                "longitude": 100.8825,
                "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=500",
                "categories": [
                    {
                        "name": "ก๋วยเตี๋ยวเรือ",
                        "items": [
                            {"name": "ก๋วยเตี๋ยวเรือเนื้อวากิว", "price": 129, "description": "เนื้อวากิวสไลซ์สุกกำลังดี น้ำซุปเข้มข้นจัดจ้าน", "image_url": "https://images.unsplash.com/photo-1569718212165-3a8278d5f624?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "crab_fried_rice_central",
                "display_name": "ข้าวผัดปู เซ็นทรัลพัทยา",
                "name": "ข้าวผัดปู เซ็นทรัลพัทยา",
                "description": "ข้าวผัดปูเนื้อก้อน หอมกลิ่นกระทะ พัทยากลาง",
                "phone_number": "0819998877",
                "address": "ถนนพัทยากลาง ตรงข้ามบิ๊กซี",
                "latitude": 12.9360,
                "longitude": 100.8840,
                "image_url": "https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=500",
                "categories": [
                    {
                        "name": "ข้าวผัด & อาหารจานเดียว",
                        "items": [
                            {"name": "ข้าวผัดปูเนื้อก้อนพิเศษ", "price": 150, "description": "ปูเนื้อก้อนโต หอมกลิ่นกระทะ เสิร์ฟพร้อมพริกน้ำปลา", "image_url": "https://images.unsplash.com/photo-1603133872878-684f208fb84b?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "pa_tim_somtam",
                "display_name": "ป้าติ๋ม ส้มตำ",
                "name": "ป้าติ๋ม ส้มตำพัทยากลาง",
                "description": "ส้มตำแซ่บ ไก่ย่างวิเชียรบุรี พัทยากลาง",
                "phone_number": "0876665544",
                "address": "พัทยากลาง สาย 3",
                "latitude": 12.9320,
                "longitude": 100.8810,
                "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=500",
                "categories": [
                    {
                        "name": "ส้มตำ & ไก่ย่าง",
                        "items": [
                            {"name": "ส้มตำไทยไข่เค็ม", "price": 70, "description": "ส้มตำไทยครบรส ใส่ไข่เค็มไชยา", "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=500"},
                            {"name": "ไก่ย่างวิเชียรบุรี (ครึ่งตัว)", "price": 120, "description": "ไก่ย่างเนื้อนุ่ม หนังกรอบ น้ำจิ้มแจ่วรสเด็ด", "image_url": "https://images.unsplash.com/photo-1562967914-608f82629710?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "mae_srinual_central",
                "display_name": "แม่ศรีนวล พัทยากลาง",
                "name": "แม่ศรีนวล พัทยากลาง",
                "description": "อาหารไทยแกงโบราณ รสชาติกลมกล่อม",
                "phone_number": "038444333",
                "address": "พัทยากลาง ซอย 12",
                "latitude": 12.9335,
                "longitude": 100.8850,
                "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500",
                "categories": [
                    {
                        "name": "แกงไทยโบราณ",
                        "items": [
                            {"name": "แกงส้มชะอมกุ้งสด", "price": 220, "description": "แกงส้มรสเข้มข้น ไข่ชะอมทอดพร้อมกุ้งสดตัวโต", "image_url": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "pu_pen_jomtien",
                "display_name": "ปูเพ็ญ หาดจอมเทียน",
                "name": "ปูเพ็ญ ซีฟู้ด หาดจอมเทียน",
                "description": "ร้านอาหารทะเลริมหาดจอมเทียน ปูนึ่งนมสดในตำนาน",
                "phone_number": "038231725",
                "address": "ริมหาดจอมเทียน พัทยาใต้",
                "latitude": 12.8885,
                "longitude": 100.8708,
                "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500",
                "categories": [
                    {
                        "name": "ซีฟู้ดหาดจอมเทียน",
                        "items": [
                            {"name": "ปูนึ่งนมสดหาดจอมเทียน", "price": 550, "description": "ปูม้านึ่งนมสด นุ่มละมุนลิ้น", "image_url": "https://images.unsplash.com/photo-1565680018434-b513d5e5fd47?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "ruan_thai_south",
                "display_name": "เรือนไทย ซีฟู้ด",
                "name": "เรือนไทย ซีฟู้ด พัทยาใต้",
                "description": "กุ้งเผาซอสซีฟู้ดมะนาวสด อาหารไทย-ทะเล บรรยากาศเรือนไทย",
                "phone_number": "038425911",
                "address": "พัทยาใต้ สาย 2",
                "latitude": 12.9248,
                "longitude": 100.8710,
                "image_url": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=500",
                "categories": [
                    {
                        "name": "เมนูกุ้งเผา",
                        "items": [
                            {"name": "กุ้งแม่น้ำเผา (500 กรัม)", "price": 490, "description": "กุ้งแม่น้ำเผา มันหัวกุ้งเยิ้มๆ พร้อมน้ำจิ้มซีฟู้ด", "image_url": "https://images.unsplash.com/photo-1559339352-11d035aa65de?w=500"}
                        ]
                    }
                ]
            },
            {
                "username": "pa_boon_somtam_south",
                "display_name": "ส้มตำป้าบุญ พัทยาใต้",
                "name": "ส้มตำป้าบุญ พัทยาใต้",
                "description": "ยำแซลมอนแซ่บ ส้มตำถาดพัทยาใต้",
                "phone_number": "0897771122",
                "address": "พัทยาใต้ ซอย 15",
                "latitude": 12.9150,
                "longitude": 100.8750,
                "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=500",
                "categories": [
                    {
                        "name": "เมนูยำ & ส้มตำ",
                        "items": [
                            {"name": "ยำแซลมอนไข่แดงเค็ม", "price": 250, "description": "แซลมอนนอร์เวย์สด ยำน้ำปลาร้าหอมไข่แดงเค็ม", "image_url": "https://images.unsplash.com/photo-1559847844-5315695dadae?w=500"}
                        ]
                    }
                ]
            }
        ]

        for item in pattaya_merchants:
            user, _ = User.objects.get_or_create(
                username=item["username"],
                defaults={
                    "display_name": item["display_name"],
                    "role": UserRole.MERCHANT
                }
            )

            merchant, created = Merchant.objects.update_or_create(
                user=user,
                defaults={
                    "name": item["name"],
                    "description": item["description"],
                    "phone_number": item["phone_number"],
                    "address": item["address"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "location": Point(item["longitude"], item["latitude"], srid=4326),
                    "image_url": item["image_url"],
                    "is_open": True,
                    "bank_account_name": f"ร้าน {item['display_name']}",
                    "bank_account_number": "1234567890",
                    "bank_name": "กสิกรไทย"
                }
            )

            for cat_data in item["categories"]:
                category, _ = Category.objects.get_or_create(
                    merchant=merchant,
                    name=cat_data["name"],
                    defaults={"sort_order": 1}
                )

                for menu_data in cat_data["items"]:
                    MenuItem.objects.update_or_create(
                        merchant=merchant,
                        category=category,
                        name=menu_data["name"],
                        defaults={
                            "price": menu_data["price"],
                            "description": menu_data["description"],
                            "image_url": menu_data["image_url"],
                            "is_available": True
                        }
                    )

        self.stdout.write(self.style.SUCCESS("Successfully seeded 10 Pattaya Merchants into PostgreSQL!"))
