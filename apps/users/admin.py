from django.contrib import admin

from apps.users.models import CustomerProfile, MerchantApplication, RiderApplication, User


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'default_delivery_address', 'registered_at')
    search_fields = ('user__display_name', 'user__line_user_id', 'user__phone_number')


@admin.register(MerchantApplication)
class MerchantApplicationAdmin(admin.ModelAdmin):
    list_display = ('store_name', 'user', 'status', 'submitted_at', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('store_name', 'user__display_name', 'user__line_user_id', 'phone_number')
    readonly_fields = ('submitted_at', 'reviewed_at', 'created_at', 'updated_at')


@admin.register(RiderApplication)
class RiderApplicationAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'vehicle_plate', 'status', 'submitted_at', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('full_name', 'user__display_name', 'user__line_user_id', 'phone_number', 'vehicle_plate')
    readonly_fields = ('submitted_at', 'reviewed_at', 'created_at', 'updated_at')


admin.site.register(User)
