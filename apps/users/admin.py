from django.contrib import admin, messages

from apps.users.models import CustomerProfile, MerchantApplication, RiderApplication, RoleChangeRequest, User
from apps.users.services import RoleChangeApprovalError, approve_role_change_request, reject_role_change_request
from apps.users.bank_encryption import BankDataEncryptionError, mask_encrypted_bank_value


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
    readonly_fields = ('masked_bank_account_name', 'masked_bank_account_number', 'masked_bank_name', 'submitted_at', 'reviewed_at', 'created_at', 'updated_at')
    exclude = ('bank_account_name_encrypted', 'bank_account_number_encrypted', 'bank_name_encrypted')

    @admin.display(description='ชื่อบัญชีรับเงิน')
    def masked_bank_account_name(self, obj):
        return self._masked_value(obj.bank_account_name_encrypted, 2)

    @admin.display(description='เลขบัญชีรับเงิน')
    def masked_bank_account_number(self, obj):
        return self._masked_value(obj.bank_account_number_encrypted)

    @admin.display(description='ธนาคาร')
    def masked_bank_name(self, obj):
        return self._masked_value(obj.bank_name_encrypted, 2)

    @staticmethod
    def _masked_value(value, visible_characters=4):
        try:
            return mask_encrypted_bank_value(value, visible_characters) if value else '-'
        except BankDataEncryptionError:
            return 'ไม่สามารถแสดงข้อมูลบัญชีได้'


@admin.register(RoleChangeRequest)
class RoleChangeRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_role', 'requested_role', 'status', 'requested_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'requested_role', 'current_role')
    search_fields = ('user__display_name', 'user__line_user_id')
    readonly_fields = ('user', 'current_role', 'requested_role', 'merchant_application', 'rider_application', 'requested_at', 'reviewed_at', 'reviewed_by')
    actions = ('approve_selected_requests', 'reject_selected_requests')

    @admin.action(description='Approve selected role-change requests')
    def approve_selected_requests(self, request, queryset):
        for role_request in queryset:
            try:
                approve_role_change_request(role_request.id, request.user, role_request.admin_note or '')
            except RoleChangeApprovalError as error:
                self.message_user(request, f'{role_request}: {error}', messages.ERROR)
            else:
                self.message_user(request, f'{role_request}: อนุมัติและสร้างสิทธิ์เรียบร้อยแล้ว', messages.SUCCESS)

    @admin.action(description='Reject selected role-change requests (admin note is required)')
    def reject_selected_requests(self, request, queryset):
        for role_request in queryset:
            try:
                reject_role_change_request(role_request.id, request.user, role_request.admin_note or '')
            except RoleChangeApprovalError as error:
                self.message_user(request, f'{role_request}: {error}', messages.ERROR)
            else:
                self.message_user(request, f'{role_request}: ไม่อนุมัติคำขอแล้ว', messages.SUCCESS)


admin.site.register(User)
