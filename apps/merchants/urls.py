from django.urls import path
from apps.merchants.views import (
    MerchantListView,
    MerchantMenuView,
    StoreStatusToggleView,
    MenuItemToggleView
)

urlpatterns = [
    path('merchants/', MerchantListView.as_view(), name='merchant-list'),
    path('merchants/<uuid:merchant_id>/menu/', MerchantMenuView.as_view(), name='merchant-menu'),
    path('merchant/store-status/', StoreStatusToggleView.as_view(), name='merchant-store-status'),
    path('merchant/menu/<uuid:item_id>/toggle/', MenuItemToggleView.as_view(), name='merchant-menu-toggle'),
]
