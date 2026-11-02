from django.contrib import admin, messages

from apps.merchants.models import BankChangeStatus, MerchantBankChangeRequest
from apps.merchants.services import BankChangeError, approve_bank_change, mask_account_number, reject_bank_change
from apps.users.bank_encryption import BankDataEncryptionError, decrypt_bank_value


@admin.register(MerchantBankChangeRequest)
class MerchantBankChangeRequestAdmin(admin.ModelAdmin):
    """
    คำขอเปลี่ยนบัญชีรับเงินของร้าน (module_32) — ใช้ได้ทันทีก่อนหน้าเว็บแอดมินเสร็จ
    ปฏิเสธ: เปิดคำขอ → กรอก "Reject reason" ≥10 ตัวอักษร → บันทึก → เลือก action "ปฏิเสธ"
    """

    list_display = ('merchant', 'status', 'new_bank', 'masked_account', 'created_at', 'reviewer', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('merchant__name',)
    readonly_fields = ('merchant', 'status', 'new_bank', 'new_account_name', 'new_account', 'reviewer', 'reviewed_at', 'created_at')
    fields = ('merchant', 'status', 'new_bank', 'new_account_name', 'new_account', 'reject_reason', 'reviewer', 'reviewed_at', 'created_at')
    actions = ('approve_selected', 'reject_selected')

    def has_add_permission(self, request):
        return False  # คำขอต้องมาจากร้านเท่านั้น

    def has_delete_permission(self, request, obj=None):
        return False  # เก็บเป็นประวัติ

    @staticmethod
    def _plain(value):
        try:
            return decrypt_bank_value(value)
        except BankDataEncryptionError:
            return '— ถอดรหัสไม่ได้ —'

    @admin.display(description='ธนาคารใหม่')
    def new_bank(self, obj):
        return self._plain(obj.bank_name_encrypted)

    @admin.display(description='ชื่อบัญชีใหม่')
    def new_account_name(self, obj):
        return self._plain(obj.bank_account_name_encrypted)

    @admin.display(description='เลขบัญชีใหม่')
    def new_account(self, obj):
        # หน้า list แสดงแบบปิดบัง หน้ารายละเอียดแสดงเต็มเพื่อให้แอดมินตรวจกับหลักฐาน
        return self._plain(obj.bank_account_number_encrypted)

    @admin.display(description='เลขบัญชีใหม่')
    def masked_account(self, obj):
        return mask_account_number(self._plain(obj.bank_account_number_encrypted))

    @admin.action(description='อนุมัติคำขอที่เลือก (เปลี่ยนบัญชีรับเงินของร้านทันที)')
    def approve_selected(self, request, queryset):
        done = 0
        for change in queryset.filter(status=BankChangeStatus.PENDING):
            try:
                approve_bank_change(change.id, request.user)
                done += 1
            except BankChangeError as error:
                self.message_user(request, f'{change.merchant}: {error}', messages.ERROR)
        if done:
            self.message_user(request, f'อนุมัติแล้ว {done} คำขอ', messages.SUCCESS)

    @admin.action(description='ปฏิเสธคำขอที่เลือก (ต้องกรอก Reject reason ไว้ก่อน)')
    def reject_selected(self, request, queryset):
        done = 0
        for change in queryset.filter(status=BankChangeStatus.PENDING):
            try:
                reject_bank_change(change.id, request.user, reason=change.reject_reason or '')
                done += 1
            except BankChangeError as error:
                self.message_user(request, f'{change.merchant}: {error}', messages.ERROR)
        if done:
            self.message_user(request, f'ปฏิเสธแล้ว {done} คำขอ', messages.WARNING)
