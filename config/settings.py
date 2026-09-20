import os
from pathlib import Path
import environ

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
}

# CORS Configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG

# GDAL & GEOS Configuration สำหรับ macOS (Homebrew Auto-Detection)
import platform
if platform.system() == 'Darwin':
    mac_gdal_path = '/opt/homebrew/opt/gdal/lib/libgdal.dylib'
    mac_geos_path = '/opt/homebrew/opt/geos/lib/libgeos_c.dylib'
    if os.path.exists(mac_gdal_path):
        GDAL_LIBRARY_PATH = mac_gdal_path
    if os.path.exists(mac_geos_path):
        GEOS_LIBRARY_PATH = mac_geos_path

