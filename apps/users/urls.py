from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from apps.users.views import (
    LineVerifyView,
    GoogleVerifyView,
    SetRoleView,
    UserProfileView,
    CustomerRegistrationView,
    MerchantApplicationView,
    RiderApplicationView,
    RegistrationStatusView,
)

urlpatterns = [
    path('auth/line-verify/', LineVerifyView.as_view(), name='line-verify'),
    path('auth/google-verify/', GoogleVerifyView.as_view(), name='google-verify'),
    path('auth/set-role/', SetRoleView.as_view(), name='set-role'),
    path('auth/me/', UserProfileView.as_view(), name='user-profile'),
    path('onboarding/customer/', CustomerRegistrationView.as_view(), name='customer-registration'),
    path('onboarding/merchant/', MerchantApplicationView.as_view(), name='merchant-application'),
    path('onboarding/rider/', RiderApplicationView.as_view(), name='rider-application'),
    path('onboarding/status/', RegistrationStatusView.as_view(), name='registration-status'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]
