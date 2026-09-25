import os
from django.contrib import admin, messages
from django.utils.html import format_html

from apps.users.models import (
    CustomerProfile, MerchantApplication, MerchantApplicationDocument,
    OnboardingIntent, RiderApplication, RiderApplicationDocument,
    RoleChangeRequest, User, ApplicationStatus, RoleChangeStatus
)
from apps.users.services import (
    RoleChangeApprovalError, approve_role_change_request, reject_role_change_request
)
from apps.users.bank_encryption import BankDataEncryptionError, decrypt_bank_value, mask_encrypted_bank_value


def render_file_preview(field_file, label='ไฟล์แนบ'):
    """
    รองรับการแสดงผลพรีวิวไฟล์หลายประเภท (รูปภาพ JPG/PNG/WEBP, PDF iframe, DOC/DOCX, TXT ฯลฯ)
    """
    if not field_file or not field_file.name:
        return format_html('<span style="color: #9ca3af; font-size: 12px;">ไม่ได้อัปโหลด</span>')

    url = field_file.url
    ext = os.path.splitext(field_file.name)[1].lower()

    # ไฟล์รูปภาพ (Image preview)
    if ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.svg']:
        return format_html(
            '<div style="margin-bottom: 8px;">'
            '<a href="{}" target="_blank" style="display: inline-block;">'
            '<img src="{}" style="max-height: 160px; max-width: 280px; border-radius: 8px; border: 1px solid #e5e7eb; object-fit: cover; box-shadow: 0 1px 3px rgba(0,0,0,0.1);" />'
            '</a><br/>'
            '<a href="{}" target="_blank" style="font-size: 11px; color: #2563eb; font-weight: 600; text-decoration: underline; margin-top: 4px; display: inline-block;">🔍 คลิกดูรูปเต็ม ({})</a>'
            '</div>',
            url, url, url, label
        )

    # ไฟล์ PDF (PDF Embedded Preview + Link)
    elif ext == '.pdf':
        return format_html(
            '<div style="margin-bottom: 8px;">'
            '<iframe src="{}" style="width: 100%; max-width: 520px; height: 220px; border-radius: 8px; border: 1px solid #d1d5db;"></iframe><br/>'
            '<a href="{}" target="_blank" style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; background: #ef521b; color: white; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600; margin-top: 6px;">'
            '📄 เปิดดูไฟล์ PDF ในแท็บใหม่ ({})</a>'
            '</div>',
            url, url, label
        )

    # ไฟล์ Word / Office / Text (Document download link)
    else:
        icon_symbol = '📝' if ext in ['.doc', '.docx', '.txt'] else '📁'
        return format_html(
            '<div style="margin-bottom: 8px;">'
            '<a href="{}" target="_blank" style="display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; background: #2563eb; color: white; border-radius: 6px; text-decoration: none; font-size: 12px; font-weight: 600;">'
            '{} เปิดอ่าน/ดาวน์โหลดไฟล์ {} ({})</a>'
            '</div>',
            url, icon_symbol, ext.upper(), label
        )


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

    @admin.display(description='พรีวิวไฟล์เอกสาร')
    def document_preview(self, obj):
        return render_file_preview(obj.document, 'เอกสารเพิ่มเติม')


class RiderApplicationDocumentInline(admin.TabularInline):
    model = RiderApplicationDocument
    extra = 0
    readonly_fields = ('document_preview', 'uploaded_at')
    can_delete = True

    @admin.display(description='พรีวิวไฟล์เอกสาร')
    def document_preview(self, obj):
        return render_file_preview(obj.document, 'เอกสารเพิ่มเติม')


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
        'single_page_approval_box',
        'user', 'maps_link',
        'preview_storefront_image', 'preview_storefront_image_2', 'preview_storefront_image_3',
        'preview_identity_document',
        'submitted_at', 'reviewed_at', 'created_at', 'updated_at'
    )
    inlines = [MerchantApplicationDocumentInline]
    actions = ('approve_selected_merchants', 'reject_selected_merchants')

    fieldsets = (
        ('⚡ ระบบอนุมัติในหน้าเดียว (Single Page Approval)', {
            'fields': ('single_page_approval_box',)
        }),
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
        ('การพิจารณาอนุมัติ (เปลี่ยนสถานะแล้วกด Save เพื่ออนุมัติทันที)', {
            'fields': ('status', 'admin_note', 'submitted_at', 'reviewed_at')
        }),
    )

    @admin.display(description='คำแนะนำการอนุมัติ')
    def single_page_approval_box(self, obj):
        role_request = getattr(obj, 'role_change_request', None)
        req_status = role_request.status if role_request else obj.status

        if req_status == 'APPROVED':
            return format_html(
                '<div style="padding: 12px 16px; background: #dcfce7; border: 1px solid #86efac; border-radius: 8px; color: #166534; font-weight: bold; font-size: 14px;">'
                '🟢 ใบสมัครร้านค้านี้ได้รับการอนุมัติเปิดร้านเรียบร้อยแล้ว'
                '</div>'
            )
        elif req_status == 'REJECTED':
            return format_html(
                '<div style="padding: 12px 16px; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px; color: #991b1b; font-weight: bold; font-size: 14px;">'
                '🔴 ใบสมัครนี้ถูกปฏิเสธแล้ว (เหตุผล: {})'
                '</div>',
                obj.admin_note or '-'
            )
        else:
            return format_html(
                '<div style="padding: 14px 16px; background: #fff7ed; border: 1px solid #fdba74; border-radius: 8px; color: #c2410c;">'
                '<div style="font-weight: bold; font-size: 14px; margin-bottom: 4px;">🟡 อยู่ระหว่างรอการตรวจสอบและอนุมัติร้านค้า</div>'
                '<div style="font-size: 12px; color: #9a3412;">💡 <b>วิธีอนุมัติจบในหน้าเดียว:</b> ปรับสถานะช่อง "Status" ด้านล่างเป็น <b>"Approved"</b> หรือ <b>"Rejected"</b> แล้วกด <b>"Save / บันทึก"</b> ที่มุมขวาล่างได้ทันที!</div>'
                '</div>'
            )

    @admin.display(description='พิกัด Google Maps')
    def maps_link(self, obj):
        return maps_link_preview(obj.google_maps_url)

    @admin.display(description='ตัวอย่างรูปหน้าร้าน 1')
    def preview_storefront_image(self, obj):
        return render_file_preview(obj.storefront_image, 'รูปหน้าร้าน 1')

    @admin.display(description='ตัวอย่างรูปหน้าร้าน 2')
    def preview_storefront_image_2(self, obj):
        return render_file_preview(obj.storefront_image_2, 'รูปหน้าร้าน 2')

    @admin.display(description='ตัวอย่างรูปหน้าร้าน 3')
    def preview_storefront_image_3(self, obj):
        return render_file_preview(obj.storefront_image_3, 'รูปหน้าร้าน 3')

    @admin.display(description='ตัวอย่างเอกสารยืนยันตัวตน')
    def preview_identity_document(self, obj):
        return render_file_preview(obj.identity_document, 'เอกสารยืนยันตัวตน')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        role_request = getattr(obj, 'role_change_request', None)
        if role_request and role_request.status == RoleChangeStatus.PENDING:
            if obj.status == ApplicationStatus.APPROVED:
                try:
                    approve_role_change_request(role_request.id, request.user, obj.admin_note or 'อนุมัติโดยแอดมิน')
                    self.message_user(request, f'อนุมัติเปิดร้าน {obj.store_name} เรียบร้อยแล้ว', messages.SUCCESS)
                except Exception as e:
                    self.message_user(request, f'เกิดข้อผิดพลาดในการอนุมัติ: {str(e)}', messages.ERROR)
            elif obj.status == ApplicationStatus.REJECTED:
                try:
                    reject_role_change_request(role_request.id, request.user, obj.admin_note or 'ไม่อนุมัติโดยแอดมิน')
                    self.message_user(request, f'ปฏิเสธใบสมัคร {obj.store_name} เรียบร้อยแล้ว', messages.WARNING)
                except Exception as e:
                    self.message_user(request, f'เกิดข้อผิดพลาดในการปฏิเสธ: {str(e)}', messages.ERROR)

    @admin.action(description='✅ อนุมัติเปิดร้านค้า (อนุมัติสิทธิ์และสร้างร้านทันที)')
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
        'single_page_approval_box',
        'user',
        'preview_driver_license', 'preview_vehicle_image', 'preview_additional_document',
        'decrypted_bank_name', 'decrypted_bank_account_name', 'decrypted_bank_account_number',
        'submitted_at', 'reviewed_at', 'created_at', 'updated_at'
    )
    exclude = ('bank_account_name_encrypted', 'bank_account_number_encrypted', 'bank_name_encrypted')
    inlines = [RiderApplicationDocumentInline]
    actions = ('approve_selected_riders', 'reject_selected_riders')

    fieldsets = (
        ('⚡ ระบบอนุมัติในหน้าเดียว (Single Page Approval)', {
            'fields': ('single_page_approval_box',)
        }),
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
        ('ข้อมูลบัญชีรับเงิน (ถอดรหัสแสดงผลเต็มสำหรับแอดมิน)', {
            'fields': ('decrypted_bank_name', 'decrypted_bank_account_name', 'decrypted_bank_account_number')
        }),
        ('การพิจารณาอนุมัติ (เปลี่ยนสถานะแล้วกด Save เพื่ออนุมัติทันที)', {
            'fields': ('status', 'admin_note', 'submitted_at', 'reviewed_at')
        }),
    )

    @admin.display(description='คำแนะนำการอนุมัติ')
    def single_page_approval_box(self, obj):
        role_request = getattr(obj, 'role_change_request', None)
        req_status = role_request.status if role_request else obj.status

        if req_status == 'APPROVED':
            return format_html(
                '<div style="padding: 12px 16px; background: #dcfce7; border: 1px solid #86efac; border-radius: 8px; color: #166534; font-weight: bold; font-size: 14px;">'
                '🟢 บัญชีไรเดอร์นี้ได้รับการอนุมัติเรียบร้อยแล้ว'
                '</div>'
            )
        elif req_status == 'REJECTED':
            return format_html(
                '<div style="padding: 12px 16px; background: #fee2e2; border: 1px solid #fca5a5; border-radius: 8px; color: #991b1b; font-weight: bold; font-size: 14px;">'
                '🔴 ใบสมัครนี้ถูกปฏิเสธแล้ว (เหตุผล: {})'
                '</div>',
                obj.admin_note or '-'
            )
        else:
            return format_html(
                '<div style="padding: 14px 16px; background: #fff7ed; border: 1px solid #fdba74; border-radius: 8px; color: #c2410c;">'
                '<div style="font-weight: bold; font-size: 14px; margin-bottom: 4px;">🟡 อยู่ระหว่างรอการตรวจสอบและอนุมัติไรเดอร์</div>'
                '<div style="font-size: 12px; color: #9a3412;">💡 <b>วิธีอนุมัติจบในหน้าเดียว:</b> ปรับสถานะช่อง "Status" ด้านล่างเป็น <b>"Approved"</b> หรือ <b>"Rejected"</b> แล้วกด <b>"Save / บันทึก"</b> ที่มุมขวาล่างได้ทันที!</div>'
                '</div>'
            )

    @admin.display(description='ตัวอย่างใบขับขี่')
    def preview_driver_license(self, obj):
        return render_file_preview(obj.driver_license_image, 'ใบขับขี่')

    @admin.display(description='ตัวอย่างรูปรถ')
    def preview_vehicle_image(self, obj):
        return render_file_preview(obj.vehicle_image, 'รูปรถ')

    @admin.display(description='ตัวอย่างเอกสารเพิ่มเติม')
    def preview_additional_document(self, obj):
        return render_file_preview(obj.additional_document, 'เอกสารเพิ่มเติม')

    @admin.display(description='ชื่อบัญชีรับเงิน')
    def decrypted_bank_account_name(self, obj):
        return self._unmasked_value(obj.bank_account_name_encrypted)

    @admin.display(description='เลขบัญชีรับเงิน (สำหรับโอนเงิน)')
    def decrypted_bank_account_number(self, obj):
        if not obj.bank_account_number_encrypted:
            return '-'
        try:
            num = decrypt_bank_value(obj.bank_account_number_encrypted)
            return format_html(
                '<span style="font-family: monospace; font-size: 15px; font-weight: bold; color: #166534; background: #dcfce7; padding: 4px 10px; border-radius: 6px; border: 1px solid #86efac; letter-spacing: 0.5px;">{}</span>',
                num
            )
        except Exception:
            return 'ไม่สามารถถอดรหัสได้'

    @admin.display(description='ธนาคาร')
    def decrypted_bank_name(self, obj):
        return self._unmasked_value(obj.bank_name_encrypted)

    @staticmethod
    def _unmasked_value(value):
        if not value:
            return '-'
        try:
            return decrypt_bank_value(value)
        except Exception:
            return 'ไม่สามารถถอดรหัสได้'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        role_request = getattr(obj, 'role_change_request', None)
        if role_request and role_request.status == RoleChangeStatus.PENDING:
            if obj.status == ApplicationStatus.APPROVED:
                try:
                    approve_role_change_request(role_request.id, request.user, obj.admin_note or 'อนุมัติโดยแอดมิน')
                    self.message_user(request, f'อนุมัติการสมัครไรเดอร์ {obj.full_name} เรียบร้อยแล้ว', messages.SUCCESS)
                except Exception as e:
                    self.message_user(request, f'เกิดข้อผิดพลาดในการอนุมัติ: {str(e)}', messages.ERROR)
            elif obj.status == ApplicationStatus.REJECTED:
                try:
                    reject_role_change_request(role_request.id, request.user, obj.admin_note or 'ไม่อนุมัติโดยแอดมิน')
                    self.message_user(request, f'ปฏิเสธใบสมัคร {obj.full_name} เรียบร้อยแล้ว', messages.WARNING)
                except Exception as e:
                    self.message_user(request, f'เกิดข้อผิดพลาดในการปฏิเสธ: {str(e)}', messages.ERROR)

    @admin.action(description='✅ อนุมัติการสมัครไรเดอร์ (อนุมัติสิทธิ์และเปิดใช้งานทันที)')
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
