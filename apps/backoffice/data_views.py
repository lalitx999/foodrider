"""
หลังบ้าน: ตารางข้อมูลอื่นๆ แบบหน้ากลาง (Module 32 เฟส B · B6)

- สร้างจาก registry: แต่ละตารางกำหนด "ช่องที่แสดง" + "ช่องค้นหา" + "การกระทำที่อนุญาต" แบบ allowlist
- ส่วนใหญ่ดูอย่างเดียว · แก้ได้เฉพาะที่ระบุไว้ (ตอนนี้: ปิดอุปกรณ์รับแจ้งเตือน)
- ไม่ส่งข้อมูลลับออกไป: FCM token แสดงแค่ต้น-ท้าย, ไม่มีบัญชีธนาคาร/ไฟล์เอกสารผู้สมัคร
- รูปหลักฐานการส่ง: ลิงก์ signed อายุสั้น (เหมือนรูปสลิป) เพราะ <img> ส่ง header ไม่ได้
"""
import math
import mimetypes
from dataclasses import dataclass, field
from typing import Callable

from django.conf import settings
from django.core import signing
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.audit import record_admin_action
from apps.notifications.models import DeviceToken, Notification
from apps.riders.models import DeliveryProof
from apps.users.media_tokens import make_media_token, read_media_token
from apps.users.models import MerchantApplication, OnboardingIntent, RiderApplication, RoleChangeRequest
from apps.users.permissions import IsAdminRole

PAGE_SIZE = 25
PROOF_TOKEN_PREFIX = 'proof:'


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error_code': code, 'message': message, 'details': []}, status=http_status)


def _user(user):
    return f'{user.display_name} <{user.email}>' if user else '—'


def _mask_token(token: str) -> str:
    return f'{token[:8]}…{token[-6:]}' if token and len(token) > 16 else '—'


def proof_file_url(request, proof: DeliveryProof, kind: str) -> str | None:
    file = proof.proof_image if kind == 'proof' else proof.signature_image
    if not file:
        return None
    token = make_media_token(f'{PROOF_TOKEN_PREFIX}{proof.id}:{kind}')
    return request.build_absolute_uri(reverse('admin-delivery-proof-file', args=[proof.id, kind, token]))


@dataclass
class Table:
    label: str
    description: str
    queryset: Callable
    columns: list[tuple[str, str]]
    row: Callable
    search: tuple[str, ...] = ()
    actions: dict = field(default_factory=dict)  # ชื่อ action → (ป้าย, เงื่อนไขแสดง(row obj) → bool)


TABLES: dict[str, Table] = {
    'notifications': Table(
        label='การแจ้งเตือน',
        description='ข้อความแจ้งเตือนที่ระบบส่งให้ผู้ใช้ทุกคน (ดูอย่างเดียว)',
        queryset=lambda: Notification.objects.select_related('user').order_by('-created_at'),
        columns=[('created_at', 'เวลา'), ('user', 'ผู้รับ'), ('title', 'หัวข้อ'), ('body', 'ข้อความ'), ('sent', 'ส่งถึงมือถือ')],
        row=lambda obj, request: {
            'created_at': obj.created_at, 'user': _user(obj.user), 'title': obj.title, 'body': obj.body,
            'sent': 'ส่งแล้ว' if obj.sent_at else 'ยังไม่ส่ง/ไม่มีอุปกรณ์',
        },
        search=('title', 'body', 'user__email', 'user__display_name'),
    ),
    'device_tokens': Table(
        label='อุปกรณ์รับแจ้งเตือน',
        description='มือถือ/เบราว์เซอร์ที่ลงทะเบียนรับแจ้งเตือน — ปิดได้ถ้าเครื่องหายหรือไม่ใช้แล้ว',
        queryset=lambda: DeviceToken.objects.select_related('user').order_by('-last_seen_at'),
        columns=[('user', 'ผู้ใช้'), ('token', 'รหัสอุปกรณ์'), ('active', 'สถานะ'), ('last_seen_at', 'ใช้ล่าสุด'), ('created_at', 'ลงทะเบียน')],
        row=lambda obj, request: {
            'user': _user(obj.user), 'token': _mask_token(obj.fcm_token), 'active': 'ใช้งาน' if obj.is_active else 'ปิดแล้ว',
            'last_seen_at': obj.last_seen_at, 'created_at': obj.created_at,
        },
        search=('user__email', 'user__display_name'),
        actions={'deactivate': ('ปิดอุปกรณ์นี้', lambda obj: obj.is_active)},
    ),
    'delivery_proofs': Table(
        label='หลักฐานการส่ง',
        description='รูปที่ไรเดอร์ถ่ายตอนส่งอาหาร (ลิงก์รูปหมดอายุใน 10 นาที — โหลดหน้าใหม่เพื่อดูอีกครั้ง)',
        queryset=lambda: DeliveryProof.objects.select_related('order', 'rider').order_by('-created_at'),
        columns=[('created_at', 'เวลา'), ('order', 'ออเดอร์'), ('rider', 'ไรเดอร์'), ('confirmed', 'ผู้รับยืนยัน'), ('proof_url', 'รูปส่งของ'), ('signature_url', 'ลายเซ็น')],
        row=lambda obj, request: {
            'created_at': obj.created_at, 'order': obj.order.order_number, 'order_id': str(obj.order_id),
            'rider': _user(obj.rider), 'confirmed': 'ใช่' if obj.recipient_confirmed else 'ไม่',
            'proof_url': proof_file_url(request, obj, 'proof'), 'signature_url': proof_file_url(request, obj, 'signature'),
        },
        search=('order__order_number', 'rider__display_name'),
    ),
    'merchant_applications': Table(
        label='ใบสมัครร้าน (ระบบเดิม)',
        description='จากช่วงที่เปิดให้ร้านภายนอกสมัคร — ดูอย่างเดียว ไม่แสดงเอกสารและบัญชีธนาคาร',
        queryset=lambda: MerchantApplication.objects.select_related('user').order_by('-created_at'),
        columns=[('created_at', 'สร้างเมื่อ'), ('store_name', 'ชื่อร้าน'), ('user', 'ผู้สมัคร'), ('phone_number', 'เบอร์'), ('status', 'สถานะ')],
        row=lambda obj, request: {
            'created_at': obj.created_at, 'store_name': obj.store_name, 'user': _user(obj.user),
            'phone_number': obj.phone_number, 'status': obj.status,
        },
        search=('store_name', 'user__email', 'phone_number'),
    ),
    'rider_applications': Table(
        label='ใบสมัครไรเดอร์ (ระบบเดิม)',
        description='จากช่วงที่เปิดให้ไรเดอร์ภายนอกสมัคร — ดูอย่างเดียว ไม่แสดงเอกสารและบัญชีธนาคาร',
        queryset=lambda: RiderApplication.objects.select_related('user').order_by('-created_at'),
        columns=[('created_at', 'สร้างเมื่อ'), ('full_name', 'ชื่อ'), ('user', 'บัญชี'), ('phone_number', 'เบอร์'), ('vehicle_plate', 'ทะเบียน'), ('status', 'สถานะ')],
        row=lambda obj, request: {
            'created_at': obj.created_at, 'full_name': obj.full_name, 'user': _user(obj.user),
            'phone_number': obj.phone_number, 'vehicle_plate': obj.vehicle_plate, 'status': obj.status,
        },
        search=('full_name', 'user__email', 'phone_number', 'vehicle_plate'),
    ),
    'role_change_requests': Table(
        label='คำขอเปลี่ยนบทบาท (ระบบเดิม)',
        description='ดูอย่างเดียว',
        queryset=lambda: RoleChangeRequest.objects.select_related('user', 'reviewed_by').order_by('-requested_at'),
        columns=[('requested_at', 'ขอเมื่อ'), ('user', 'ผู้ใช้'), ('change', 'เปลี่ยน'), ('status', 'สถานะ'), ('reviewed_by', 'ผู้ตรวจ')],
        row=lambda obj, request: {
            'requested_at': obj.requested_at, 'user': _user(obj.user), 'change': f'{obj.current_role} → {obj.requested_role}',
            'status': obj.status, 'reviewed_by': obj.reviewed_by.display_name if obj.reviewed_by else '—',
        },
        search=('user__email', 'user__display_name'),
    ),
    'onboarding_intents': Table(
        label='การเลือกบทบาทตอนสมัคร',
        description='ผู้ใช้เลือกบทบาทอะไรตอนสมัครครั้งแรก (ดูอย่างเดียว)',
        queryset=lambda: OnboardingIntent.objects.select_related('user').order_by('-selected_at'),
        columns=[('selected_at', 'เลือกเมื่อ'), ('user', 'ผู้ใช้'), ('selected_role', 'บทบาทที่เลือก'), ('status', 'สถานะ')],
        row=lambda obj, request: {
            'selected_at': obj.selected_at, 'user': _user(obj.user), 'selected_role': obj.selected_role, 'status': obj.status,
        },
        search=('user__email', 'user__display_name'),
    ),
}


class AdminDataTablesView(APIView):
    """GET /data/ — รายชื่อตารางที่ดูได้ + จำนวนแถว"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        return Response({
            'success': True,
            'data': [
                {'key': key, 'label': table.label, 'description': table.description, 'count': table.queryset().count()}
                for key, table in TABLES.items()
            ],
        })


class AdminDataTableView(APIView):
    """GET /data/<key>/?q=&page="""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request, key):
        table = TABLES.get(key)
        if table is None:
            return _error('TABLE_NOT_FOUND', 'ไม่พบตารางนี้', status.HTTP_404_NOT_FOUND)
        rows = table.queryset()
        keyword = (request.query_params.get('q') or '').strip()
        if keyword and table.search:
            condition = Q()
            for lookup in table.search:
                condition |= Q(**{f'{lookup}__icontains': keyword})
            rows = rows.filter(condition)
        total = rows.count()
        try:
            page = max(1, int(request.query_params.get('page', 1)))
        except (TypeError, ValueError):
            page = 1
        objects = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        data = []
        for obj in objects:
            values = table.row(obj, request)
            values['id'] = str(obj.pk)
            values['actions'] = [name for name, (_, allowed) in table.actions.items() if allowed(obj)]
            data.append(values)
        return Response({
            'success': True,
            'data': data,
            'meta': {
                'key': key,
                'label': table.label,
                'description': table.description,
                'columns': [{'key': column, 'label': label} for column, label in table.columns],
                'action_labels': {name: label for name, (label, _) in table.actions.items()},
                'searchable': bool(table.search),
                'page': page,
                'total': total,
                'total_pages': max(1, math.ceil(total / PAGE_SIZE)),
            },
        })


class AdminDataActionView(APIView):
    """POST /data/<key>/<id>/<action>/ — เฉพาะ action ใน allowlist ของตาราง"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, key, pk, action):
        table = TABLES.get(key)
        if table is None or action not in table.actions:
            return _error('ACTION_NOT_ALLOWED', 'ทำรายการนี้กับตารางนี้ไม่ได้', status.HTTP_403_FORBIDDEN)
        obj = table.queryset().filter(pk=pk).first()
        if obj is None:
            return _error('NOT_FOUND', 'ไม่พบข้อมูลนี้', status.HTTP_404_NOT_FOUND)
        _, allowed = table.actions[action]
        if not allowed(obj):
            return _error('ACTION_NOT_ALLOWED', 'ทำรายการนี้กับข้อมูลนี้ไม่ได้แล้ว', status.HTTP_409_CONFLICT)

        if key == 'device_tokens' and action == 'deactivate':
            with transaction.atomic():
                obj.is_active = False
                obj.save(update_fields=['is_active'])
                record_admin_action(
                    request.user, 'device_token.deactivate', target_type='user', target_id=obj.user_id,
                    target_label=obj.user.display_name, changes={'device': {'from': 'ใช้งาน', 'to': 'ปิดแล้ว'}},
                    note=_mask_token(obj.fcm_token), request=request,
                )
            return Response({'success': True, 'message': 'ปิดอุปกรณ์นี้แล้ว'})
        return _error('ACTION_NOT_ALLOWED', 'ทำรายการนี้ไม่ได้', status.HTTP_403_FORBIDDEN)


class AdminDeliveryProofFileView(APIView):
    """GET /delivery-proofs/<uuid>/<kind>/<token>/ — รูปหลักฐานการส่ง (signed token, ไม่ต้องใช้ header)"""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'media'

    def get(self, request, proof_id, kind, token):
        if kind not in ('proof', 'signature'):
            return _error('NOT_FOUND', 'ไม่พบไฟล์', status.HTTP_404_NOT_FOUND)
        try:
            payload = read_media_token(token)
        except signing.BadSignature:  # รวม SignatureExpired
            return _error('MEDIA_TOKEN_INVALID', 'ลิงก์รูปหมดอายุหรือไม่ถูกต้อง — โหลดหน้าใหม่', status.HTTP_403_FORBIDDEN)
        if payload.get('id') != f'{PROOF_TOKEN_PREFIX}{proof_id}:{kind}':
            return _error('MEDIA_TOKEN_INVALID', 'ลิงก์รูปไม่ถูกต้อง', status.HTTP_403_FORBIDDEN)

        proof = DeliveryProof.objects.filter(pk=proof_id).first()
        file = (proof.proof_image if kind == 'proof' else proof.signature_image) if proof else None
        if not file or not default_storage.exists(file.name):
            return _error('NOT_FOUND', 'ไม่พบไฟล์', status.HTTP_404_NOT_FOUND)

        content_type = mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
        if getattr(settings, 'USE_X_ACCEL_REDIRECT', False):
            # production: nginx เสิร์ฟจาก internal location /media/ (ไม่เปิดสาธารณะ — deploy/nginx.conf)
            response = HttpResponse(content_type=content_type)
            response['X-Accel-Redirect'] = f"{settings.MEDIA_URL.rstrip('/')}/{file.name}"
            response['Content-Disposition'] = 'inline'
            return response
        return FileResponse(default_storage.open(file.name, 'rb'), content_type=content_type)
