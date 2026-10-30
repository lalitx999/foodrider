import os
from decimal import Decimal
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

# อ่าน Environment Variables จากไฟล์ .env
BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(
    DJANGO_DEBUG=(bool, False)
)
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env('DJANGO_DEBUG', default=False)
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=['127.0.0.1', 'localhost'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',  # PostGIS GeoDjango Extension

    # Third-Party Apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',

    # Local Project Apps
    'apps.users',
    'apps.merchants',
    'apps.orders',
    'apps.payments',
    'apps.riders',
    'apps.notifications',
]


MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ฐานข้อมูล PostgreSQL พร้อม PostGIS Driver (ห้ามใช้ SQLite เด็ดขาด)
DATABASES = {
    'default': env.db_url(
        'DATABASE_URL',
        default=f"postgis://{env('DATABASE_USER')}:{env('DATABASE_PASSWORD')}@{env('DATABASE_HOST')}:{env('DATABASE_PORT')}/{env('DATABASE_NAME')}"
    )
}

AUTH_USER_MODEL = 'users.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'th-th'
TIME_ZONE = 'Asia/Bangkok'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# ไฟล์สลิปเก็บนอก MEDIA_ROOT (P0-05/P0-11) — เข้าถึงได้เฉพาะ signed endpoint
SLIP_STORAGE_LOCATION = env('SLIP_STORAGE_LOCATION', default=os.path.join(BASE_DIR, 'private_media'))
# production: ให้ nginx เสิร์ฟไฟล์เองผ่าน internal location (X-Accel-Redirect)
USE_X_ACCEL_REDIRECT = env.bool('USE_X_ACCEL_REDIRECT', default=not DEBUG)
X_ACCEL_REDIRECT_PREFIX = env('X_ACCEL_REDIRECT_PREFIX', default='/private-media/')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    # Throttling (P0-09): ป้องกันการยิงถล่ม login / อัปโหลดสลิป / quote
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'anon': '60/min',
        'user': '300/min',
        'login': '10/min',
        'register': '5/min',
        'slip': '10/hour',
        'quote': '120/hour',
        'admin': '1200/hour',
        'media': '600/hour',
    },
}

# CORS Configuration
# Production must explicitly list every frontend origin that may call this API.
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
if DEBUG:
    # ระหว่างพัฒนาบนเครื่อง ให้ frontend ที่รันที่ 3000 เรียก API ได้เสมอ
    CORS_ALLOWED_ORIGINS += ['http://localhost:3000', 'http://127.0.0.1:3000']
CORS_ALLOWED_ORIGINS = list(dict.fromkeys(CORS_ALLOWED_ORIGINS))
# ไม่ใช้ regex กว้าง ๆ (เดิมเปิด *.vercel.app ทั้งหมด) — ต้องระบุ origin ตรงตัวเท่านั้น
CORS_ALLOWED_ORIGIN_REGEXES = env.list('CORS_ALLOWED_ORIGIN_REGEXES', default=[])
# ระบบใช้ JWT ผ่าน Authorization header ไม่ได้พึ่ง cookie ข้ามโดเมน จึงปิด credentials
CORS_ALLOW_CREDENTIALS = env.bool('CORS_ALLOW_CREDENTIALS', default=False)
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])

# HTTPS is terminated by the reverse proxy in production. These settings make
# Django treat the forwarded protocol as authoritative and protect browser
# sessions and sensitive response data.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env.bool('DJANGO_SECURE_SSL_REDIRECT', default=not DEBUG)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'
SECURE_HSTS_SECONDS = env.int('DJANGO_SECURE_HSTS_SECONDS', default=0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=14),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}


# ---------------------------------------------------------------------------
# Domain settings (P0-01 / P0-15 / P0-12) — อ่านจาก env เท่านั้น ห้าม hardcode ในโค้ด
# ---------------------------------------------------------------------------
PAYMENT_VERIFICATION_MODE = env('PAYMENT_VERIFICATION_MODE', default='MANUAL').upper()
if PAYMENT_VERIFICATION_MODE not in {'MANUAL', 'API', 'HYBRID'}:
    raise ImproperlyConfigured(
        'PAYMENT_VERIFICATION_MODE ต้องเป็นหนึ่งใน MANUAL / API / HYBRID '
        f'(ได้รับค่า: {PAYMENT_VERIFICATION_MODE!r})'
    )

SLIP_MAX_ATTEMPTS = env.int('SLIP_MAX_ATTEMPTS', default=3)
SLIP_MAX_FILE_BYTES = env.int('SLIP_MAX_FILE_BYTES', default=5 * 1024 * 1024)
SLIP_SIGNED_URL_TTL_SECONDS = env.int('SLIP_SIGNED_URL_TTL_SECONDS', default=600)
SLIP_REVIEW_SLA_MINUTES = env.int('SLIP_REVIEW_SLA_MINUTES', default=15)

# ค่าจัดส่ง (BR-7): 3 กม.แรก 30 บาท ไรเดอร์ 25 / เกิน กม.ละ 6 บาท ไรเดอร์ 5
DELIVERY_BASE_FARE = Decimal(env('DELIVERY_BASE_FARE', default='30.00'))
DELIVERY_BASE_DISTANCE_KM = Decimal(env('DELIVERY_BASE_DISTANCE_KM', default='3.00'))
DELIVERY_PER_KM_FARE = Decimal(env('DELIVERY_PER_KM_FARE', default='6.00'))
RIDER_BASE_EARNING = Decimal(env('RIDER_BASE_EARNING', default='25.00'))
RIDER_PER_KM_EARNING = Decimal(env('RIDER_PER_KM_EARNING', default='5.00'))
MAX_DELIVERY_DISTANCE_KM = Decimal(env('MAX_DELIVERY_DISTANCE_KM', default='15'))

MAX_SEARCH_RADIUS_KM = env.float('MAX_SEARCH_RADIUS_KM', default=15.0)
DEFAULT_SEARCH_RADIUS_KM = env.float('DEFAULT_SEARCH_RADIUS_KM', default=10.0)


# GDAL & GEOS Configuration สำหรับ macOS (Homebrew Auto-Detection)
import platform
if platform.system() == 'Darwin':
    mac_gdal_path = '/opt/homebrew/opt/gdal/lib/libgdal.dylib'
    mac_geos_path = '/opt/homebrew/opt/geos/lib/libgeos_c.dylib'
    if os.path.exists(mac_gdal_path):
        GDAL_LIBRARY_PATH = mac_gdal_path
    if os.path.exists(mac_geos_path):
        GEOS_LIBRARY_PATH = mac_geos_path

# Celery & Redis Configuration
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
