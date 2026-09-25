from django.urls import path
from apps.merchants.views import (
    MerchantListView,
    MerchantMenuView,
    StoreStatusToggleView,
    MenuItemToggleView,
    MerchantDashboardView,
    MenuItemCreateView,
    MenuItemDetailView,
    CategoryManageView,
)

urlpatterns = [
    path('merchants/', MerchantListView.as_view(), name='merchant-list'),
    path('merchants/<uuid:merchant_id>/menu/', MerchantMenuView.as_view(), name='merchant-menu'),
    path('merchant/store-status/', StoreStatusToggleView.as_view(), name='merchant-store-status'),
    path('merchant/dashboard/', MerchantDashboardView.as_view(), name='merchant-dashboard'),
    path('merchant/categories/', CategoryManageView.as_view(), name='merchant-categories'),
    path('merchant/menu/', MenuItemCreateView.as_view(), name='merchant-menu-create'),
    path('merchant/menu/<uuid:item_id>/', MenuItemDetailView.as_view(), name='merchant-menu-detail'),
    path('merchant/menu/<uuid:item_id>/toggle/', MenuItemToggleView.as_view(), name='merchant-menu-toggle'),
]
