# ขึ้นหลังบ้านบน VPS (Module 33 · S-5)

ทุกขั้นในไฟล์นี้เป็น **R0: คุณรันเองบน VPS** ตามลำดับ

```
อินเทอร์เน็ต ──443──> Caddy (HTTPS อัตโนมัติ) ──> nginx (static/media/สลิป) ──> gunicorn (Django)
                                                                        ├─ db (PostGIS)   ไม่เปิดพอร์ตออกนอก
                                                                        ├─ redis          ไม่เปิดพอร์ตออกนอก
                                                                        └─ celery worker / beat
```

## 0. ก่อนเริ่ม

- VPS: Ubuntu 22.04/24.04 แรม 2 GB ขึ้นไป (ถ้าได้ 1 GB ให้ตั้ง `GUNICORN_WORKERS=2` และเปิด swap 2 GB)
- DNS ที่ผู้ให้บริการโดเมน: เพิ่ม **A record** `api` → IP ของ VPS
  แล้วรอให้ `ping api.<โดเมนคุณ>` ตอบเป็น IP ของ VPS ก่อนทำข้อ 4 (ไม่งั้น Caddy ขอ HTTPS ไม่ผ่าน)
- Firewall ที่หน้าเว็บผู้ให้บริการ VPS (ถ้ามี): เปิด 22, 80, 443 เท่านั้น

## 1. ตั้งเครื่อง (ทำครั้งเดียว)

```bash
ssh root@<IP ของ VPS>
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443/tcp && ufw allow 443/udp && ufw --force enable
```

> Docker เปิดพอร์ตผ่าน ufw ได้เอง ไฟล์ compose นี้จึง **ไม่ publish** พอร์ต db / redis / 8000 เลย เปิดแค่ 80/443 ของ Caddy

## 2. ดึงโค้ด

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/lalitx999/foodrider.git
cd foodrider
```

(repo เป็น private → ใช้ Personal Access Token ของ GitHub แทนรหัสผ่าน หรือเพิ่ม deploy key)

## 3. ไฟล์ .env

```bash
cp .env.example .env
nano .env
```

ค่าที่ต้องเปลี่ยน:

| ตัวแปร | ใส่อะไร |
|---|---|
| `API_DOMAIN`, `DJANGO_ALLOWED_HOSTS` | `api.<โดเมนคุณ>` |
| `DJANGO_SECRET_KEY` | รัน `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DATABASE_PASSWORD` | รหัสยาวๆ (สร้างด้วยคำสั่งเดียวกัน) — ห้ามใช้ค่าตัวอย่าง |
| `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | URL หน้าเว็บจริง เช่น `https://<โดเมนคุณ>` (ถ้ายังใช้ Vercel ใส่ URL ของ Vercel ด้วย คั่นด้วย `,`) |
| `BANK_DATA_ENCRYPTION_KEY` | รัน `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (บน Mac ใน venv ก็ได้) |
| `GOOGLE_CLIENT_ID` | ค่าเดียวกับที่ frontend ใช้ |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | ดูด้านล่าง |
| `PLATFORM_PROMPTPAY_ACCOUNT` | พร้อมเพย์ของร้าน |
| `SLIP_VERIFY_*` | เว้นไว้ก่อนจนกว่าจะได้คีย์ (S-4) — `PAYMENT_VERIFICATION_MODE=MANUAL` |

**Firebase JSON ต้องอยู่บรรทัดเดียว** — บน Mac รัน (ไม่ต้องส่งไฟล์ไปที่อื่น):

```bash
python3 -c "import json; print(json.dumps(json.load(open('firebase-config.json'))))"
```

คัดลอกผลลัพธ์ทั้งบรรทัดไปวางหลัง `FIREBASE_SERVICE_ACCOUNT_JSON=` ในไฟล์ `.env` บน VPS

```bash
chmod 600 .env
```

## 4. รัน

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps          # ทุกตัวต้อง Up
docker compose -f docker-compose.prod.yml logs -f caddy   # รอเห็น "certificate obtained successfully" แล้ว Ctrl+C
```

## 5. ฐานข้อมูล + static (ครั้งแรก และทุกครั้งที่อัปเดตโค้ด)

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
docker compose -f docker-compose.prod.yml exec backend python manage.py collectstatic --noinput
docker compose -f docker-compose.prod.yml exec backend python manage.py check --deploy
```

## 6. สร้างร้าน / ไรเดอร์ / แอดมิน

```bash
# ร้าน (สาขา 1) — ใช้พิกัดจริงของร้าน คัดลอกจาก Google Maps (กดค้างที่ร้าน)
docker compose -f docker-compose.prod.yml exec backend python manage.py create_branch \
  --email shop@<โดเมนคุณ> --display-name "ชื่อร้าน" --phone 0xxxxxxxxx \
  --name "ชื่อร้าน" --address "ที่อยู่ร้าน" --lat 12.xxxxxx --lng 100.xxxxxx

# ไรเดอร์ (น้องชาย)
docker compose -f docker-compose.prod.yml exec backend python manage.py create_rider \
  --email rider@<โดเมนคุณ> --display-name "ชื่อไรเดอร์" --phone 0xxxxxxxxx --vehicle-plate "กข 1234"
```

ทั้งสองคำสั่งจะถามรหัสผ่าน 2 รอบ (อย่างน้อย 12 ตัว) — พิมพ์บน VPS เท่านั้น

แอดมิน: สมัครเป็นลูกค้าผ่านหน้าเว็บด้วยอีเมลของคุณก่อน แล้วรัน

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py promote_admin you@example.com
```

## 7. เช็กว่าใช้ได้

```bash
curl -I https://api.<โดเมนคุณ>/api/v1/merchants/
```

ควรได้ `HTTP/2 200` (หรือ 401 ถ้า endpoint ต้องล็อกอิน) ไม่ใช่ error ใบรับรอง
แล้วตั้ง `NEXT_PUBLIC_API_BASE_URL` ของ frontend เป็น `https://api.<โดเมนคุณ>/api/v1` แล้ว redeploy

## อัปเดตโค้ดรอบถัดไป

```bash
cd /opt/foodrider
git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend python manage.py migrate
docker compose -f docker-compose.prod.yml exec backend python manage.py collectstatic --noinput
```

## สำรองฐานข้อมูล

```bash
docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > /root/backup-$(date +%F).sql.gz
```

ดาวน์โหลดไฟล์สำรองเก็บนอก VPS เป็นระยะ

## ห้ามทำ

- `docker compose down -v` — `-v` ลบ volume = **ลบฐานข้อมูลและรูปทั้งหมด**
- commit `.env` / `firebase-config.json`
- เปิดพอร์ต 5432 / 6379 ออกอินเทอร์เน็ต
