from django.urls import path
from apps.orders.views import (
    OrderQuoteView,
    CreateOrderView,
    UploadSlipView,
    OrderDetailView,
    MerchantOrderListView,
    OrderStatusUpdateView,
    CustomerOrderListView,
    PaymentQRView,
)

urlpatterns = [
    path('orders/quote/', OrderQuoteView.as_view(), name='order-quote'),
    path('payments/promptpay-qr/', PaymentQRView.as_view(), name='payment-promptpay-qr'),
    path('orders/merchant-orders/', MerchantOrderListView.as_view(), name='merchant-orders'),
    path('orders/my-orders/', CustomerOrderListView.as_view(), name='customer-orders'),
    path('orders/', CreateOrderView.as_view(), name='order-create'),
    path('orders/<uuid:order_id>/upload-slip/', UploadSlipView.as_view(), name='order-upload-slip'),
    path('orders/<uuid:order_id>/status/', OrderStatusUpdateView.as_view(), name='order-status-update'),
    path('orders/<uuid:order_id>/', OrderDetailView.as_view(), name='order-detail'),
]
