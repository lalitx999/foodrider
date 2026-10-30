from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = 'apps.orders'
    verbose_name = 'Orders'

    def ready(self):
        # ลงทะเบียน django system checks ของค่าจัดส่ง BR-7 (P0-15)
        from apps.orders import checks  # noqa: F401
