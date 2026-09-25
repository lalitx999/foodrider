from django.urls import path
from apps.riders.views import (
    RiderStatusToggleView,
    AvailableJobsListView,
    ClaimJobView,
    CompleteJobView,
    MerchantOrderReadyView,
    RiderJobHistoryView,
    RiderWalletView,
)

urlpatterns = [
    path('rider/status/', RiderStatusToggleView.as_view(), name='rider-status'),
    path('rider/orders/available/', AvailableJobsListView.as_view(), name='rider-jobs-available'),
    path('rider/orders/history/', RiderJobHistoryView.as_view(), name='rider-jobs-history'),
    path('rider/wallet/', RiderWalletView.as_view(), name='rider-wallet'),
    path('rider/orders/<uuid:order_id>/claim/', ClaimJobView.as_view(), name='rider-job-claim'),
    path('rider/orders/<uuid:order_id>/complete/', CompleteJobView.as_view(), name='rider-job-complete'),
    path('merchant/orders/<uuid:order_id>/ready/', MerchantOrderReadyView.as_view(), name='merchant-order-ready'),
]
