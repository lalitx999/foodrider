from django.contrib import admin, messages
from django.utils.html import format_html

from apps.users.models import (
    CustomerProfile, MerchantApplication, MerchantApplicationDocument,
    OnboardingIntent, RiderApplication, RiderApplicationDocument,
    RoleChangeRequest, User
)
from apps.users.services import (
    RoleChangeApprovalError, approve_role_change_request, reject_role_change_request
)
from apps.users.bank_encryption import BankDataEncryptionError, mask_encrypted_bank_value


def image_preview(field_file, label='ดูรูปภาพ'):
    if field_file:
        return format_html(
            '<a href="{}" target="_blank" style="display: inline-block; margin-right: 8px; margin-bottom: 8px;">'
            '<img src="{}" style="max-height: 140px; max-width: 220px; border-radius: 8px; border: 1px solid #e5e7eb; object-fit: cover; box-shadow: 0 1px 3px rgba(0,0,0,0.1);" />'
            '<br/><span style="font-size: 11px; color: #4b5563; font-weight: 500;">🔍 คลิกรูปใหญ่ ({})</span></a>',
            field_file.url, field_file.url, label
        )
    return format_html('<span style="color: #9ca3af; font-size: 12px;">ไม่ได้อัปโหลด</span>')


def file_preview(field_file, label='ดูเอกสาร'):
    if field_file:
        return format_html(
            '<a href="{}" target="_blank" style="display: inline-inline-flex; align-items: center; padding: 6px 14px; background: #ef521b; color: white; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600;">'
            '📄 เปิดดูเอกสาร ({})</a>',
            field_file.url, label
        )
    return format_html('<span style="color: #9ca3af; font-size: 12px;">ไม่ได้แนบเอกสาร</span>')


def maps_link_preview(url):
    if url:
        return format_html(
            '<a href="{}" target="_blank" style="color: #2563eb; font-weight: bold; text-decoration: underline; font-size: 13px;">'
            '📍 คลิกเพื่อเปิด Google Maps ในแท็บใหม่</a>',
            url
        )
    return format_html('<span style="color: #9ca3af; font-size: 12px;">ไม่มีลิงก์</span>')


class MerchantApplicationDocumentInline(admin.TabularInline):
    model = MerchantApplicationDocument
    extra = 0
    readonly_fields = ('document_preview', 'uploaded_at')
    can_delete = True

    @admin.display(description='ไฟล์เอกสารแนบเพิ่มเติม')
    def document_preview(self, obj):
        return file_preview(obj.document, 'เอกสารเพิ่มเติม')


class RiderApplicationDocumentInline(admin.TabularInline):
    model = RiderApplicationDocument
    extra = 0
    readonly_fields = ('document_preview', 'uploaded_at')
    can_delete = True

    @admin.display(description='ไฟล์เอกสารแนบเพิ่มเติม')
    def document_preview(self, obj):
        return file_preview(obj.document, 'เอกสารเพิ่มเติม')


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'default_delivery_address', 'maps_link', 'registered_at')
    search_fields = ('user__display_name', 'user__email', 'user__phone_number')

    @admin.display(description='พิกัด Google Maps')
    def maps_link(self, obj):
        return maps_link_preview(obj.google_maps_url)


@admin.register(OnboardingIntent)
class OnboardingIntentAdmin(admin.ModelAdmin):
    list_display = ('user', 'selected_role', 'status', 'selected_at', 'completed_at')
    list_filter = ('selected_role', 'status')
    search_fields = ('user__display_name', 'user__email')
    readonly_fields = ('user', 'selected_role', 'status', 'selected_at', 'completed_at')


@admin.register(MerchantApplication)
class MerchantApplicationAdmin(admin.ModelAdmin):
    list_display = ('store_name', 'user', 'phone_number', 'bank_name', 'status', 'submitted_at', 'reviewed_at')
    list_filter = ('status', 'bank_name')
    search_fields = ('store_name', 'user__display_name', 'user__email', 'phone_number', 'bank_account_number')
    readonly_fields = (
        'user', 'maps_link',
        'preview_storefront_image', 'preview_storefront_image_2', 'preview_storefront_image_3',
        'preview_identity_document',
        'submitted_at', 'reviewed_at', 'created_at', 'updated_at'
    )
    inlines = [MerchantApplicationDocumentInline]
    actions = ('approve_selected_merchants', 'reject_selected_merchants')

    fieldsets = (
        ('ข้อมูลทั่วไปของร้านค้า', {
            'fields': ('user', 'store_name', 'phone_number', 'address', 'google_maps_url', 'maps_link')
        }),
        ('ภาพถ่ายหน้าร้าน (3 ภาพบังคับ)', {
            'fields': (
                ('storefront_image', 'preview_storefront_image'),
                ('storefront_image_2', 'preview_storefront_image_2'),
                ('storefront_image_3', 'preview_storefront_image_3'),
            )
        }),
        ('เอกสารยืนยันตัวตน', {
            'fields': ('identity_document', 'preview_identity_document')
        }),
        ('ข้อมูลบัญชีธนาคารสำหรับโอนเงิน', {
            'fields': ('bank_name', 'bank_account_name', 'bank_account_number')
        }),
        ('การพิจารณาอนุมัติ', {
            'fields': ('status', 'admin_note', 'submitted_at', 'reviewed_at')
        }),
    )

    @admin.display(description='พิกัด Google Maps')
    def maps_link(self, obj):
        return maps_link_preview(obj.google_maps_url)

    @admin.display(description='ตัวอย่างรูปหน้าร้าน 1')
    def preview_storefront_image(self, obj):
        return image_preview(obj.storefront_image, 'รูปที่ 1')

    @admin.display(description='ตัวอย่างรูปหน้าร้าน 2')
    def preview_storefront_image_2(self, obj):
        return image_preview(obj.storefront_image_2, 'รูปที่ 2')

    @admin.display(description='ตัวอย่างรูปหน้าร้าน 3')
    def preview_storefront_image_3(self, obj):
        return image_preview(obj.storefront_image_3, 'รูปที่ 3')

    @admin.display(description='ตัวอย่างเอกสารยืนยันตัวตน')
    def preview_identity_document(self, obj):
        return file_preview(obj.identity_document, 'บัตรประชาชน/ทะเบียนร้าน')

    @admin.action(description='✅ อนุมัติเปิดร้านค้า (อนุมัติสิทธิ์และสร้างร้านทันทีในขั้นตอนเดียว)')
    def approve_selected_merchants(self, request, queryset):
        count = 0
        for app in queryset:
            role_request = getattr(app, 'role_change_request', None)
            if not role_request:
                self.message_user(request, f'ร้าน {app.store_name}: ไม่พบคำขอเปลี่ยนสิทธิ์ในระบบ', messages.ERROR)
                continue
            try:
                approve_role_change_request(role_request.id, request.user, app.admin_note or 'อนุมัติโดยแอดมิน')
                count += 1
            except Exception as e:
                self.message_user(request, f'ร้าน {app.store_name}: {str(e)}', messages.ERROR)

        if count > 0:
            self.message_user(request, f'อนุมัติร้านค้าเรียบร้อยแล้วจำนวน {count} รายการ', messages.SUCCESS)

    @admin.action(description='❌ ปฏิเสธ/ไม่อนุมัติใบสมัครร้านค้า')
    def reject_selected_merchants(self, request, queryset):
        count = 0
        for app in queryset:
            role_request = getattr(app, 'role_change_request', None)
            if not role_request:
                self.message_user(request, f'ร้าน {app.store_name}: ไม่พบคำขอเปลี่ยนสิทธิ์ในระบบ', messages.ERROR)
                continue
            try:
                reject_role_change_request(role_request.id, request.user, app.admin_note or 'ข้อมูลไม่ครบถ้วนหรือไม่ผ่านเกณฑ์')
                count += 1
            except Exception as e:
                self.message_user(request, f'ร้าน {app.store_name}: {str(e)}', messages.ERROR)

        if count > 0:
            self.message_user(request, f'ปฏิเสธใบสมัครร้านค้าจำนวน {count} รายการแล้ว', messages.WARNING)


@admin.register(RiderApplication)
class RiderApplicationAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'phone_number', 'vehicle_plate', 'status', 'submitted_at', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('full_name', 'user__display_name', 'user__email', 'phone_number', 'vehicle_plate')
    readonly_fields = (
        'user',
        'preview_driver_license', 'preview_vehicle_image', 'preview_additional_document',
        'masked_bank_account_name', 'masked_bank_account_number', 'masked_bank_name',
        'submitted_at', 'reviewed_at', 'created_at', 'updated_at'
    )
    exclude = ('bank_account_name_encrypted', 'bank_account_number_encrypted', 'bank_name_encrypted')
    inlines = [RiderApplicationDocumentInline]
    actions = ('approve_selected_riders', 'reject_selected_riders')

    fieldsets = (
        ('ข้อมูลส่วนตัวไรเดอร์', {
            'fields': ('user', 'full_name', 'phone_number', 'vehicle_plate')
        }),
        ('ภาพถ่ายใบขับขี่และรถ', {
            'fields': (
                ('driver_license_image', 'preview_driver_license'),
                ('vehicle_image', 'preview_vehicle_image'),
            )
        }),
        ('เอกสารเพิ่มเติมหลัก', {
            'fields': ('additional_document', 'preview_additional_document')
        }),
        ('ข้อมูลบัญชีรับเงิน (ข้อมูลถูกเข้ารหัสปลอดภัย)', {
            'fields': ('masked_bank_name', 'masked_bank_account_name', 'masked_bank_account_number')
        }),
        ('การพิจารณาอนุมัติ', {
            'fields': ('status', 'admin_note', 'submitted_at', 'reviewed_at')
        }),
    )

    @admin.display(description='ตัวอย่างใบขับขี่')
    def preview_driver_license(self, obj):
        return image_preview(obj.driver_license_image, 'ใบขับขี่')

    @admin.display(description='ตัวอย่างรูปรถ')
    def preview_vehicle_image(self, obj):
        return image_preview(obj.vehicle_image, 'รูปรถ')

    @admin.display(description='ตัวอย่างเอกสารเพิ่มเติม')
    def preview_additional_document(self, obj):
        return file_preview(obj.additional_document, 'เอกสารเพิ่มเติม')

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

    @admin.action(description='✅ อนุมัติการสมัครไรเดอร์ (อนุมัติสิทธิ์และเปิดใช้งานทันทีในขั้นตอนเดียว)')
    def approve_selected_riders(self, request, queryset):
        count = 0
        for app in queryset:
            role_request = getattr(app, 'role_change_request', None)
            if not role_request:
                self.message_user(request, f'ไรเดอร์ {app.full_name}: ไม่พบคำขอเปลี่ยนสิทธิ์ในระบบ', messages.ERROR)
                continue
            try:
                approve_role_change_request(role_request.id, request.user, app.admin_note or 'อนุมัติโดยแอดมิน')
                count += 1
            except Exception as e:
                self.message_user(request, f'ไรเดอร์ {app.full_name}: {str(e)}', messages.ERROR)

        if count > 0:
            self.message_user(request, f'อนุมัติไรเดอร์เรียบร้อยแล้วจำนวน {count} รายการ', messages.SUCCESS)

    @admin.action(description='❌ ปฏิเสธ/ไม่อนุมัติใบสมัครไรเดอร์')
    def reject_selected_riders(self, request, queryset):
        count = 0
        for app in queryset:
            role_request = getattr(app, 'role_change_request', None)
            if not role_request:
                self.message_user(request, f'ไรเดอร์ {app.full_name}: ไม่พบคำขอเปลี่ยนสิทธิ์ในระบบ', messages.ERROR)
                continue
            try:
                reject_role_change_request(role_request.id, request.user, app.admin_note or 'ข้อมูลไม่ครบถ้วนหรือไม่ผ่านเกณฑ์')
                count += 1
            except Exception as e:
                self.message_user(request, f'ไรเดอร์ {app.full_name}: {str(e)}', messages.ERROR)

        if count > 0:
            self.message_user(request, f'ปฏิเสธใบสมัครไรเดอร์จำนวน {count} รายการแล้ว', messages.WARNING)


@admin.register(RoleChangeRequest)
class RoleChangeRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_role', 'requested_role', 'status', 'requested_at', 'reviewed_by', 'reviewed_at')
    list_filter = ('status', 'requested_role', 'current_role')
    search_fields = ('user__display_name', 'user__email')
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
