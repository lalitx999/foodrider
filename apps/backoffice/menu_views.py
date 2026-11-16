"""
หลังบ้าน: เมนูอาหารของทุกสาขา (Module 32 เฟส B · B3)

- แอดมินแก้เมนูของสาขาไหนก็ได้ (ร้านแก้เองได้เหมือนเดิมจากจอครัว)
- เมนูที่เคยถูกสั่งแล้ว "ลบ" = ซ่อน (OrderItem อ้างแบบ RESTRICT, ประวัติออเดอร์ต้องอยู่ครบ — P0-13)
- ทุกการแก้ไขเขียน AdminAuditLog พร้อมค่าเดิม → ค่าใหม่
"""
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.audit import diff, record_admin_action
from apps.merchants.models import Category, Merchant, MenuItem, MenuOption
from apps.merchants.serializers import MenuItemSerializer
from apps.merchants.validators import validate_uploaded_image
from apps.orders.models import OrderItem
from apps.users.permissions import IsAdminRole

MAX_PRICE = Decimal('100000')
MAX_OPTIONS = 30


class MenuInputError(Exception):
    pass


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({'success': False, 'error_code': code, 'message': message, 'details': []}, status=http_status)


def _money(raw, label: str) -> Decimal:
    try:
        value = Decimal(str(raw).strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        raise MenuInputError(f'{label}ต้องเป็นตัวเลข')
    if value != value or value < 0 or value > MAX_PRICE:
        raise MenuInputError(f'{label}ต้องอยู่ระหว่าง 0 ถึง {MAX_PRICE:,.0f} บาท')
    return value


def _bool(raw) -> bool:
    return raw if isinstance(raw, bool) else str(raw).lower() in ('1', 'true', 'yes', 'on')


def _parse_options(raw) -> list[dict]:
    """ตัวเลือกเสริม: [{"name": "ไข่ดาว", "extra_price": 10}] (multipart ส่งมาเป็น JSON string)"""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or '[]')
        except ValueError:
            raise MenuInputError('รูปแบบตัวเลือกเสริมไม่ถูกต้อง')
    if not isinstance(raw, list):
        raise MenuInputError('รูปแบบตัวเลือกเสริมไม่ถูกต้อง')
    if len(raw) > MAX_OPTIONS:
        raise MenuInputError(f'ตัวเลือกเสริมได้ไม่เกิน {MAX_OPTIONS} รายการ')
    options = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise MenuInputError('รูปแบบตัวเลือกเสริมไม่ถูกต้อง')
        name = str(entry.get('name') or '').strip()
        if not name:
            continue
        if len(name) > 100:
            raise MenuInputError('ชื่อตัวเลือกเสริมยาวเกิน 100 ตัวอักษร')
        options.append({'name': name, 'extra_price': _money(entry.get('extra_price') or 0, f'ราคาเพิ่มของ "{name}" ')})
    return options


def _options_summary(item: MenuItem) -> str:
    # อ่านจาก DB ตรงๆ (ไม่ใช้ prefetch cache ที่อาจเก่าหลังแทนที่ตัวเลือก)
    options = MenuOption.objects.filter(menu_item=item).order_by('name')
    return ', '.join(f'{option.name} +{option.extra_price}' for option in options) or '—'


def _item_snapshot(item: MenuItem) -> dict:
    return {
        'name': item.name,
        'price': item.price,
        'description': item.description or '',
        'category': item.category.name if item.category else None,
        'is_available': item.is_available,
        'options': _options_summary(item),
    }


def _get_branch(branch_id):
    return Merchant.objects.filter(pk=branch_id).first()


def _category_for(branch: Merchant, raw_id):
    if raw_id in (None, '', 'null'):
        return None
    category = Category.objects.filter(pk=raw_id, merchant=branch).first() if _is_uuid(raw_id) else None
    if category is None:
        raise MenuInputError('หมวดหมู่นี้ไม่ใช่ของสาขานี้')
    return category


def _is_uuid(value) -> bool:
    import uuid

    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _validated_image(request):
    image = request.FILES.get('image')
    if image is None:
        return None
    try:
        return validate_uploaded_image(image)
    except serializers.ValidationError as error:
        raise MenuInputError(' '.join(str(message) for message in error.detail))


def _apply_item_fields(item: MenuItem, branch: Merchant, data, request, *, creating: bool):
    if creating or 'name' in data:
        name = str(data.get('name') or '').strip()
        if not name:
            raise MenuInputError('กรุณาระบุชื่อเมนู')
        if len(name) > 255:
            raise MenuInputError('ชื่อเมนูยาวเกิน 255 ตัวอักษร')
        item.name = name
    if creating or 'price' in data:
        if data.get('price') in (None, ''):
            raise MenuInputError('กรุณาระบุราคา')
        item.price = _money(data.get('price'), 'ราคา')
    if 'description' in data:
        item.description = str(data.get('description') or '').strip()[:2000]
    if 'category_id' in data:
        item.category = _category_for(branch, data.get('category_id'))
    if 'is_available' in data:
        item.is_available = _bool(data.get('is_available'))
    image = _validated_image(request)
    if image is not None:
        item.image = image
    elif _bool(data.get('remove_image')):
        item.image = None
        item.image_url = ''


def _replace_options(item: MenuItem, options: list[dict]) -> None:
    item.options.all().delete()
    MenuOption.objects.bulk_create([MenuOption(menu_item=item, **option) for option in options])


def _serialize_item(item: MenuItem, request) -> dict:
    data = MenuItemSerializer(item, context={'request': request}).data
    data['has_orders'] = OrderItem.objects.filter(menu_item=item).exists()
    return data


class AdminBranchMenuView(APIView):
    """GET /branches/<id>/menu/ — หมวดหมู่ + ทุกเมนู (รวมที่ปิดขาย) + ตัวเลือกเสริม"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request, branch_id):
        branch = _get_branch(branch_id)
        if branch is None:
            return _error('BRANCH_NOT_FOUND', 'ไม่พบสาขานี้', status.HTTP_404_NOT_FOUND)
        items = list(
            MenuItem.objects.filter(merchant=branch).select_related('category').prefetch_related('options').order_by('name')
        )
        ordered = set(OrderItem.objects.filter(menu_item__in=items).values_list('menu_item_id', flat=True).distinct())

        def row(item):
            data = MenuItemSerializer(item, context={'request': request}).data
            data['has_orders'] = item.id in ordered
            return data

        categories = []
        for category in Category.objects.filter(merchant=branch).order_by('sort_order', 'name'):
            categories.append({
                'id': str(category.id),
                'name': category.name,
                'sort_order': category.sort_order,
                'items': [row(item) for item in items if item.category_id == category.id],
            })
        return Response({
            'success': True,
            'data': {
                'branch': {'id': str(branch.id), 'name': branch.name, 'is_open': branch.is_open},
                'categories': categories,
                'uncategorized': [row(item) for item in items if item.category_id is None],
            },
        })


class AdminCategoryCreateView(APIView):
    """POST /branches/<id>/categories/ {name, sort_order?}"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, branch_id):
        branch = _get_branch(branch_id)
        if branch is None:
            return _error('BRANCH_NOT_FOUND', 'ไม่พบสาขานี้', status.HTTP_404_NOT_FOUND)
        name = str(request.data.get('name') or '').strip()
        if not name or len(name) > 100:
            return _error('INVALID_CATEGORY', 'ชื่อหมวดหมู่ต้องมี 1–100 ตัวอักษร')
        if Category.objects.filter(merchant=branch, name__iexact=name).exists():
            return _error('DUPLICATE_CATEGORY', f'มีหมวดหมู่ "{name}" อยู่แล้ว')
        try:
            sort_order = int(request.data.get('sort_order', Category.objects.filter(merchant=branch).count()))
        except (TypeError, ValueError):
            return _error('INVALID_CATEGORY', 'ลำดับต้องเป็นตัวเลข')
        with transaction.atomic():
            category = Category.objects.create(merchant=branch, name=name, sort_order=sort_order)
            record_admin_action(
                request.user, 'category.create', target_type='branch', target_id=branch.pk,
                target_label=f'{branch.name} · หมวด {name}', changes={'category': {'from': None, 'to': name}}, request=request,
            )
        return Response({'success': True, 'data': {'id': str(category.id), 'name': category.name, 'sort_order': category.sort_order}},
                        status=status.HTTP_201_CREATED)


class AdminCategoryDetailView(APIView):
    """PATCH /categories/<id>/ {name?, sort_order?} · DELETE = ลบหมวด (เมนูข้างในย้ายไป "ไม่มีหมวดหมู่")"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def _get(self, category_id):
        return Category.objects.select_related('merchant').filter(pk=category_id).first()

    def patch(self, request, category_id):
        category = self._get(category_id)
        if category is None:
            return _error('CATEGORY_NOT_FOUND', 'ไม่พบหมวดหมู่นี้', status.HTTP_404_NOT_FOUND)
        before = {'name': category.name, 'sort_order': category.sort_order}
        if 'name' in request.data:
            name = str(request.data.get('name') or '').strip()
            if not name or len(name) > 100:
                return _error('INVALID_CATEGORY', 'ชื่อหมวดหมู่ต้องมี 1–100 ตัวอักษร')
            if Category.objects.filter(merchant=category.merchant, name__iexact=name).exclude(pk=category.pk).exists():
                return _error('DUPLICATE_CATEGORY', f'มีหมวดหมู่ "{name}" อยู่แล้ว')
            category.name = name
        if 'sort_order' in request.data:
            try:
                category.sort_order = int(request.data.get('sort_order'))
            except (TypeError, ValueError):
                return _error('INVALID_CATEGORY', 'ลำดับต้องเป็นตัวเลข')
        changes = diff(before, {'name': category.name, 'sort_order': category.sort_order})
        with transaction.atomic():
            category.save()
            if changes:
                record_admin_action(
                    request.user, 'category.update', target_type='branch', target_id=category.merchant_id,
                    target_label=f'{category.merchant.name} · หมวด {category.name}', changes=changes, request=request,
                )
        return Response({'success': True, 'data': {'id': str(category.id), 'name': category.name, 'sort_order': category.sort_order}})

    def delete(self, request, category_id):
        category = self._get(category_id)
        if category is None:
            return _error('CATEGORY_NOT_FOUND', 'ไม่พบหมวดหมู่นี้', status.HTTP_404_NOT_FOUND)
        moved = category.items.count()
        with transaction.atomic():
            record_admin_action(
                request.user, 'category.delete', target_type='branch', target_id=category.merchant_id,
                target_label=f'{category.merchant.name} · หมวด {category.name}',
                changes={'category': {'from': category.name, 'to': None}},
                note=f'ย้ายเมนู {moved} รายการไป "ไม่มีหมวดหมู่"' if moved else '', request=request,
            )
            category.delete()  # MenuItem.category เป็น SET_NULL — เมนูไม่หาย
        return Response({'success': True, 'message': 'ลบหมวดหมู่แล้ว' + (f' (ย้ายเมนู {moved} รายการไป "ไม่มีหมวดหมู่")' if moved else '')})


class AdminMenuItemCreateView(APIView):
    """POST /branches/<id>/menu-items/ (JSON หรือ multipart เมื่อมีรูป)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def post(self, request, branch_id):
        branch = _get_branch(branch_id)
        if branch is None:
            return _error('BRANCH_NOT_FOUND', 'ไม่พบสาขานี้', status.HTTP_404_NOT_FOUND)
        item = MenuItem(merchant=branch, is_available=True)
        try:
            _apply_item_fields(item, branch, request.data, request, creating=True)
            options = _parse_options(request.data.get('options', '[]'))
        except MenuInputError as error:
            return _error('INVALID_MENU_ITEM', str(error))
        with transaction.atomic():
            item.save()
            _replace_options(item, options)
            record_admin_action(
                request.user, 'menu.create', target_type='branch', target_id=branch.pk,
                target_label=f'{branch.name} · {item.name}', changes=diff({}, _item_snapshot(item)), request=request,
            )
        return Response({'success': True, 'data': _serialize_item(item, request)}, status=status.HTTP_201_CREATED)


class AdminMenuItemDetailView(APIView):
    """PATCH /menu-items/<id>/ · DELETE = ลบ (ถ้าเคยถูกสั่ง = ซ่อนแทน)"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def _get(self, item_id):
        return MenuItem.objects.select_related('merchant', 'category').prefetch_related('options').filter(pk=item_id).first()

    def patch(self, request, item_id):
        item = self._get(item_id)
        if item is None:
            return _error('MENU_ITEM_NOT_FOUND', 'ไม่พบเมนูนี้', status.HTTP_404_NOT_FOUND)
        before = _item_snapshot(item)
        try:
            _apply_item_fields(item, item.merchant, request.data, request, creating=False)
            options = _parse_options(request.data['options']) if 'options' in request.data else None
        except MenuInputError as error:
            return _error('INVALID_MENU_ITEM', str(error))
        with transaction.atomic():
            item.save()
            if options is not None:
                _replace_options(item, options)
            item.refresh_from_db()
            changes = diff(before, _item_snapshot(item))
            if 'image' in request.FILES or _bool(request.data.get('remove_image')):
                changes['image'] = {'from': None, 'to': 'เปลี่ยนรูป' if 'image' in request.FILES else 'ลบรูป'}
            if changes:
                action = 'menu.toggle' if set(changes) == {'is_available'} else 'menu.update'
                record_admin_action(
                    request.user, action, target_type='branch', target_id=item.merchant_id,
                    target_label=f'{item.merchant.name} · {item.name}', changes=changes, request=request,
                )
        return Response({'success': True, 'data': _serialize_item(item, request)})

    def delete(self, request, item_id):
        item = self._get(item_id)
        if item is None:
            return _error('MENU_ITEM_NOT_FOUND', 'ไม่พบเมนูนี้', status.HTTP_404_NOT_FOUND)
        label = f'{item.merchant.name} · {item.name}'
        with transaction.atomic():
            if OrderItem.objects.filter(menu_item=item).exists():
                was = item.is_available
                item.is_available = False
                item.save(update_fields=['is_available', 'updated_at'])
                record_admin_action(
                    request.user, 'menu.hide', target_type='branch', target_id=item.merchant_id, target_label=label,
                    changes={'is_available': {'from': was, 'to': False}}, note='เคยถูกสั่งแล้ว จึงซ่อนแทนการลบ', request=request,
                )
                return Response({'success': True, 'data': {'id': str(item.id), 'hidden': True},
                                 'message': 'เมนูนี้เคยถูกสั่งแล้ว จึงซ่อนแทนการลบ (ประวัติออเดอร์ยังอยู่ครบ)'})
            record_admin_action(
                request.user, 'menu.delete', target_type='branch', target_id=item.merchant_id, target_label=label,
                changes=diff(_item_snapshot(item), {key: None for key in _item_snapshot(item)}), request=request,
            )
            item.delete()
        return Response({'success': True, 'data': {'id': str(item_id), 'hidden': False}, 'message': 'ลบเมนูแล้ว'})
