"""
หลังบ้าน: ข้อมูลสาขา + คำขอเปลี่ยนบัญชีรับเงิน (Module 32 เฟส B · B4)

ใช้ตัวตรวจข้อมูล/บริการชุดเดียวกับที่ร้านแก้เองจากจอครัว (MerchantProfileUpdateSerializer,
update_merchant_profile, approve/reject_bank_change) — ไม่มีทางลัดที่ข้ามการตรวจ
"""
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.audit import diff, record_admin_action
from apps.merchants.models import BankChangeStatus, Merchant, MerchantBankChangeRequest
from apps.merchants.serializers import MerchantProfileUpdateSerializer
from apps.merchants.services import BankChangeError, approve_bank_change, reject_bank_change, update_merchant_profile
from apps.merchants.views import _profile_payload
from apps.users.bank_encryption import BankDataEncryptionError, decrypt_bank_value
from apps.users.permissions import IsAdminRole

PROFILE_FIELDS = ('name', 'description', 'phone_number', 'address', 'latitude', 'longitude', 'is_open')


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST, details=None):
    return Response({'success': False, 'error_code': code, 'message': message, 'details': details or []}, status=http_status)


def _snapshot(merchant: Merchant) -> dict:
    return {
        'name': merchant.name,
        'description': merchant.description or '',
        'phone_number': merchant.phone_number,
        'address': merchant.address,
        'latitude': f'{merchant.latitude:.7f}' if merchant.latitude is not None else None,
        'longitude': f'{merchant.longitude:.7f}' if merchant.longitude is not None else None,
        'is_open': merchant.is_open,
    }


def _branch_payload(request, merchant: Merchant) -> dict:
    data = _profile_payload(request, merchant)
    data.update({
        'email': merchant.user.email,
        'is_active': merchant.user.is_active,
        'created_at': merchant.created_at,
    })
    return data


class AdminBranchProfileView(APIView):
    """GET/PATCH /branches/<id>/profile/ — แก้ชื่อ เบอร์ ที่อยู่ พิกัด รูป คำอธิบาย และเปิด/ปิดร้าน"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def _get(self, branch_id):
        return Merchant.objects.select_related('user').filter(pk=branch_id).first()

    def get(self, request, branch_id):
        merchant = self._get(branch_id)
        if merchant is None:
            return _error('BRANCH_NOT_FOUND', 'ไม่พบสาขานี้', status.HTTP_404_NOT_FOUND)
        return Response({'success': True, 'data': _branch_payload(request, merchant)})

    def patch(self, request, branch_id):
        merchant = self._get(branch_id)
        if merchant is None:
            return _error('BRANCH_NOT_FOUND', 'ไม่พบสาขานี้', status.HTTP_404_NOT_FOUND)
        serializer = MerchantProfileUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return _error('INVALID_PAYLOAD', 'ข้อมูลไม่ถูกต้อง', details=serializer.errors)
        data = dict(serializer.validated_data)
        image = data.pop('image', None)

        is_open = None
        if 'is_open' in request.data:
            raw = request.data.get('is_open')
            is_open = raw if isinstance(raw, bool) else str(raw).lower() in ('1', 'true', 'yes', 'on')
            if is_open and not merchant.user.is_active:
                return _error('BRANCH_INACTIVE', 'สาขานี้ถูกปิดการใช้งาน — เปิดการใช้งานก่อนเปิดร้าน', status.HTTP_409_CONFLICT)

        before = _snapshot(merchant)
        with transaction.atomic():
            merchant = update_merchant_profile(merchant, data, image=image)
            if is_open is not None and is_open != merchant.is_open:
                merchant.is_open = is_open
                merchant.save(update_fields=['is_open', 'updated_at'])
            changes = diff(before, _snapshot(merchant))
            if image is not None:
                changes['image'] = {'from': None, 'to': 'เปลี่ยนรูปหน้าร้าน'}
            if changes:
                record_admin_action(
                    request.user, 'branch.update', target_type='branch', target_id=merchant.pk,
                    target_label=merchant.name, changes=changes, request=request,
                )
        merchant.refresh_from_db()
        return Response({'success': True, 'data': _branch_payload(request, merchant), 'message': 'บันทึกข้อมูลสาขาแล้ว'})


def _decrypt(value: str) -> str:
    try:
        return decrypt_bank_value(value)
    except BankDataEncryptionError:
        return ''


def serialize_bank_change(change: MerchantBankChangeRequest) -> dict:
    """แอดมินเห็นเลขบัญชีเต็ม (ต้องใช้ตรวจก่อนอนุมัติ) — ฝั่งร้านเห็นแค่ 4 ตัวท้าย"""
    merchant = change.merchant
    return {
        'id': str(change.id),
        'status': change.status,
        'branch': {'id': str(merchant.id), 'name': merchant.name},
        'current': {
            'bank_name': merchant.bank_name,
            'bank_account_name': merchant.bank_account_name,
            'bank_account_number': merchant.bank_account_number,
        },
        'requested': {
            'bank_name': _decrypt(change.bank_name_encrypted),
            'bank_account_name': _decrypt(change.bank_account_name_encrypted),
            'bank_account_number': _decrypt(change.bank_account_number_encrypted),
        },
        'reviewer': change.reviewer.display_name if change.reviewer else None,
        'reviewed_at': change.reviewed_at,
        'reject_reason': change.reject_reason or '',
        'created_at': change.created_at,
    }


class AdminBankChangeListView(APIView):
    """GET /bank-changes/?status=PENDING — คำขอเปลี่ยนบัญชีรับเงินของสาขา"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        changes = MerchantBankChangeRequest.objects.select_related('merchant', 'reviewer').order_by('-created_at')
        wanted = (request.query_params.get('status') or '').upper()
        if wanted:
            if wanted not in BankChangeStatus.values:
                return _error('INVALID_STATUS', f'สถานะไม่ถูกต้อง: {wanted}')
            changes = changes.filter(status=wanted)
        return Response({
            'success': True,
            'data': [serialize_bank_change(change) for change in changes[:100]],
            'meta': {'pending_total': MerchantBankChangeRequest.objects.filter(status=BankChangeStatus.PENDING).count()},
        })


def _bank_error(error: BankChangeError):
    http_status = {
        'BANK_CHANGE_NOT_FOUND': status.HTTP_404_NOT_FOUND,
        'REJECT_REASON_REQUIRED': status.HTTP_400_BAD_REQUEST,
    }.get(error.code, status.HTTP_409_CONFLICT)
    return _error(error.code, str(error), http_status)


class AdminBankChangeApproveView(APIView):
    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, change_id):
        try:
            with transaction.atomic():
                before = MerchantBankChangeRequest.objects.select_related('merchant').filter(pk=change_id).first()
                old_account = before.merchant.bank_account_number if before else ''
                change = approve_bank_change(change_id, request.user)
                change.merchant.refresh_from_db()
                record_admin_action(
                    request.user, 'bank_change.approve', target_type='branch', target_id=change.merchant_id,
                    target_label=change.merchant.name,
                    changes={'bank_account_number': {'from': _mask(old_account), 'to': _mask(change.merchant.bank_account_number)}},
                    request=request,
                )
        except BankChangeError as error:
            return _bank_error(error)
        return Response({'success': True, 'data': serialize_bank_change(change), 'message': 'อนุมัติบัญชีใหม่แล้ว'})


class AdminBankChangeRejectView(APIView):
    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, change_id):
        reason = str(request.data.get('reason') or '')
        try:
            with transaction.atomic():
                change = reject_bank_change(change_id, request.user, reason=reason)
                record_admin_action(
                    request.user, 'bank_change.reject', target_type='branch', target_id=change.merchant_id,
                    target_label=change.merchant.name, note=reason.strip(), request=request,
                )
        except BankChangeError as error:
            return _bank_error(error)
        return Response({'success': True, 'data': serialize_bank_change(change), 'message': 'ปฏิเสธคำขอแล้ว'})


def _mask(number: str) -> str:
    """บันทึกการแก้ไขเก็บแค่ 4 ตัวท้ายของเลขบัญชี"""
    digits = ''.join(ch for ch in (number or '') if ch.isdigit())
    return f'***{digits[-4:]}' if digits else '—'
