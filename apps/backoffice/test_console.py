import json
import os
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from apps.backoffice.models import AdminAuditLog
from apps.merchants.models import BankChangeStatus, Category, Merchant, MenuItem, MenuOption, MerchantBankChangeRequest
from apps.merchants.services import submit_bank_change
from apps.notifications.models import DeviceToken, Notification
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.riders.models import DeliveryProof, RiderProfile
from apps.users.models import CustomerProfile, User, UserRole


def png(name='x.png'):
    buffer = BytesIO()
    Image.new('RGB', (8, 8), color='red').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class ConsoleBase(TestCase):
    def setUp(self):
        cache.clear()
        media = tempfile.mkdtemp(prefix='food-admin-test-')
        override = override_settings(MEDIA_ROOT=media, USE_X_ACCEL_REDIRECT=False)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, media, True)
        patch('apps.backoffice.order_actions.create_and_send_notification').start()
        patch('apps.notifications.fcm.create_and_send_notification').start()
        self.addCleanup(patch.stopall)

        self.client = APIClient()
        self.admin = User.objects.create(display_name='เจ้าของ', email='owner@example.com', role=UserRole.ADMIN, is_staff=True)
        self.client.force_authenticate(self.admin)
        kitchen = User.objects.create(display_name='ครัว', email='kitchen@example.com', role=UserRole.MERCHANT)
        self.branch = Merchant.objects.create(
            user=kitchen, name='สาขา 1', image_url='https://example.com/s.png', phone_number='0811111111', address='ถนน 1',
            latitude=Decimal('12.92'), longitude=Decimal('100.88'), location=Point(100.88, 12.92, srid=4326),
            is_open=False, bank_account_name='ร้าน', bank_account_number='2108583463', bank_name='กสิกรไทย',
        )
        self.customer = User.objects.create(display_name='ลูกค้า', email='c@example.com', role=UserRole.CUSTOMER, phone_number='0899999999')
        CustomerProfile.objects.create(user=self.customer, default_delivery_address='บ้าน')

    def make_order(self, order_status=OrderStatus.COMPLETED, number='ORD-C-1', item=None, paid=True):
        order = Order.objects.create(
            order_number=number, customer=self.customer, merchant=self.branch, status=order_status,
            subtotal=Decimal('100.00'), delivery_fee=Decimal('30.00'), total_amount=Decimal('130.00'),
            delivery_address='บ้าน', delivery_latitude=Decimal('12.93'), delivery_longitude=Decimal('100.89'),
            delivery_distance_km=Decimal('2.00'), rider_delivery_fee=Decimal('25.00'), platform_fee=Decimal('15.00'),
            paid_at=timezone.now() if paid else None,
        )
        if item:
            OrderItem.objects.create(order=order, menu_item=item, item_name=item.name, unit_price=item.price, quantity=2, total_price=item.price * 2)
        return order


class MenuAdminTests(ConsoleBase):
    def test_full_menu_lifecycle_is_audited(self):
        category = self.client.post(reverse('admin-category-create', args=[self.branch.id]), {'name': 'ข้าว'}, format='json')
        self.assertEqual(category.status_code, status.HTTP_201_CREATED, category.data)
        duplicate = self.client.post(reverse('admin-category-create', args=[self.branch.id]), {'name': 'ข้าว'}, format='json')
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        created = self.client.post(reverse('admin-menu-item-create', args=[self.branch.id]), {
            'name': 'ข้าวกะเพรา', 'price': '55', 'category_id': category.data['data']['id'],
            'options': json.dumps([{'name': 'ไข่ดาว', 'extra_price': 10}]), 'image': png(),
        }, format='multipart')
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        item = MenuItem.objects.get()
        self.assertEqual(item.price, Decimal('55.00'))
        self.assertTrue(item.image)
        self.assertEqual(list(item.options.values_list('name', flat=True)), ['ไข่ดาว'])

        updated = self.client.patch(reverse('admin-menu-item-detail', args=[item.id]), {
            'price': '60', 'options': [{'name': 'ไข่ดาว', 'extra_price': 12}, {'name': 'พิเศษ', 'extra_price': 15}],
        }, format='json')
        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.data)
        log = AdminAuditLog.objects.filter(action='menu.update').get()
        self.assertEqual(log.changes['price'], {'from': '55.00', 'to': '60.00'})
        self.assertIn('พิเศษ', log.changes['options']['to'])

        toggled = self.client.patch(reverse('admin-menu-item-detail', args=[item.id]), {'is_available': False}, format='json')
        self.assertFalse(toggled.data['data']['is_available'])
        self.assertTrue(AdminAuditLog.objects.filter(action='menu.toggle').exists())

        menu = self.client.get(reverse('admin-branch-menu', args=[self.branch.id])).data['data']
        self.assertEqual(menu['categories'][0]['items'][0]['name'], 'ข้าวกะเพรา')  # รวมเมนูที่ปิดขาย

        deleted_category = self.client.delete(reverse('admin-category-detail', args=[category.data['data']['id']]))
        self.assertEqual(deleted_category.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertIsNone(item.category)  # เมนูไม่หาย ย้ายไปไม่มีหมวด

    def test_invalid_input_and_cross_branch_category_rejected(self):
        other_user = User.objects.create(display_name='ครัว2', email='k2@example.com', role=UserRole.MERCHANT)
        other = Merchant.objects.create(
            user=other_user, name='สาขา 2', image_url='x', phone_number='0', address='a', latitude=1, longitude=1,
            bank_account_name='-', bank_account_number='-', bank_name='-',
        )
        foreign = Category.objects.create(merchant=other, name='ของสาขา 2')
        url = reverse('admin-menu-item-create', args=[self.branch.id])
        for payload in (
            {'name': '', 'price': '10'},
            {'name': 'ก', 'price': '-1'},
            {'name': 'ก', 'price': 'abc'},
            {'name': 'ก', 'price': '10', 'category_id': str(foreign.id)},
            {'name': 'ก', 'price': '10', 'options': 'not-json'},
        ):
            response = self.client.post(url, payload, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, payload)
        self.assertFalse(MenuItem.objects.filter(merchant=self.branch).exists())

    def test_delete_ordered_item_hides_instead(self):
        item = MenuItem.objects.create(merchant=self.branch, name='ผัดไทย', price=Decimal('50'))
        self.make_order(item=item)
        response = self.client.delete(reverse('admin-menu-item-detail', args=[item.id]))
        self.assertTrue(response.data['data']['hidden'])
        item.refresh_from_db()
        self.assertFalse(item.is_available)

        fresh = MenuItem.objects.create(merchant=self.branch, name='ใหม่', price=Decimal('10'))
        MenuOption.objects.create(menu_item=fresh, name='เพิ่ม', extra_price=Decimal('5'))
        response = self.client.delete(reverse('admin-menu-item-detail', args=[fresh.id]))
        self.assertFalse(response.data['data']['hidden'])
        self.assertFalse(MenuItem.objects.filter(pk=fresh.pk).exists())


class BranchAdminTests(ConsoleBase):
    def test_edit_profile_and_open_store_with_audit(self):
        url = reverse('admin-branch-profile', args=[self.branch.id])
        response = self.client.patch(url, {'name': 'สาขา 1 บางแสน', 'is_open': True, 'latitude': 13.28, 'longitude': 100.92}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.name, 'สาขา 1 บางแสน')
        self.assertTrue(self.branch.is_open)
        self.assertAlmostEqual(self.branch.location.y, 13.28, places=4)
        log = AdminAuditLog.objects.get(action='branch.update')
        self.assertEqual(log.changes['is_open'], {'from': False, 'to': True})

        bad = self.client.patch(url, {'latitude': 0, 'longitude': 0}, format='json')
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inactive_branch_cannot_be_opened(self):
        self.branch.user.is_active = False
        self.branch.user.save()
        response = self.client.patch(reverse('admin-branch-profile', args=[self.branch.id]), {'is_open': True}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch.dict(os.environ, {'BANK_DATA_ENCRYPTION_KEY': Fernet.generate_key().decode()})
    def test_bank_change_approve_and_reject(self):
        change = submit_bank_change(self.branch, bank_name='ไทยพาณิชย์', bank_account_name='ร้านใหม่', bank_account_number='1234567890')
        listing = self.client.get(reverse('admin-bank-change-list'), {'status': 'PENDING'})
        self.assertEqual(listing.data['meta']['pending_total'], 1)
        self.assertEqual(listing.data['data'][0]['requested']['bank_account_number'], '1234567890')

        response = self.client.post(reverse('admin-bank-change-approve', args=[change.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.branch.refresh_from_db()
        self.assertEqual(self.branch.bank_account_number, '1234567890')
        log = AdminAuditLog.objects.get(action='bank_change.approve')
        self.assertEqual(log.changes['bank_account_number'], {'from': '***3463', 'to': '***7890'})
        self.assertNotIn('1234567890', json.dumps(log.changes))

        again = self.client.post(reverse('admin-bank-change-approve', args=[change.id]))
        self.assertEqual(again.status_code, status.HTTP_409_CONFLICT)

        second = submit_bank_change(self.branch, bank_name='x', bank_account_name='y', bank_account_number='999')
        short = self.client.post(reverse('admin-bank-change-reject', args=[second.id]), {'reason': 'สั้น'}, format='json')
        self.assertEqual(short.status_code, status.HTTP_400_BAD_REQUEST)
        ok = self.client.post(reverse('admin-bank-change-reject', args=[second.id]), {'reason': 'ชื่อบัญชีไม่ตรงกับชื่อร้าน'}, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertEqual(MerchantBankChangeRequest.objects.get(pk=second.pk).status, BankChangeStatus.REJECTED)


class UserAdminTests(ConsoleBase):
    def test_list_search_and_detail_stats(self):
        self.make_order()
        listing = self.client.get(reverse('admin-user-list'), {'q': '0899999999'})
        self.assertEqual([row['email'] for row in listing.data['data']], ['c@example.com'])
        self.assertEqual(listing.data['meta']['role_counts']['ADMIN'], 1)

        detail = self.client.get(reverse('admin-user-detail', args=[self.customer.id])).data['data']
        self.assertEqual(detail['stats']['completed'], 1)
        self.assertEqual(detail['stats']['spent'], '130.00')
        self.assertEqual(detail['customer_profile']['default_delivery_address'], 'บ้าน')

    def test_role_switch_rules(self):
        url = reverse('admin-user-role', args=[self.customer.id])
        self.assertEqual(self.client.post(url, {'role': 'MERCHANT'}, format='json').status_code, status.HTTP_400_BAD_REQUEST)
        promoted = self.client.post(url, {'role': 'ADMIN'}, format='json')
        self.assertEqual(promoted.status_code, status.HTTP_200_OK, promoted.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.role, UserRole.ADMIN)
        self.assertTrue(self.customer.is_staff)

        self_change = self.client.post(reverse('admin-user-role', args=[self.admin.id]), {'role': 'CUSTOMER'}, format='json')
        self.assertEqual(self_change.status_code, status.HTTP_409_CONFLICT)

        kitchen = self.client.post(reverse('admin-user-role', args=[self.branch.user.id]), {'role': 'ADMIN'}, format='json')
        self.assertEqual(kitchen.status_code, status.HTTP_409_CONFLICT)

        demoted = self.client.post(url, {'role': 'CUSTOMER'}, format='json')
        self.assertEqual(demoted.status_code, status.HTTP_200_OK)
        self.assertTrue(AdminAuditLog.objects.filter(action='user.role').count() == 2)

    def test_cannot_remove_last_admin_or_self(self):
        other_admin = User.objects.create(display_name='แอดมิน 2', email='a2@example.com', role=UserRole.ADMIN)
        # ปิดแอดมินอีกคนได้ (ยังเหลือเรา)
        ok = self.client.patch(reverse('admin-user-detail', args=[other_admin.id]), {'is_active': False}, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        # ปิดตัวเองไม่ได้
        self_off = self.client.patch(reverse('admin-user-detail', args=[self.admin.id]), {'is_active': False}, format='json')
        self.assertEqual(self_off.status_code, status.HTTP_409_CONFLICT)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_deactivate_customer_and_merchant_rules(self):
        response = self.client.patch(reverse('admin-user-detail', args=[self.customer.id]), {'is_active': False, 'display_name': 'ลูกค้า X'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertEqual(self.customer.display_name, 'ลูกค้า X')

        self.make_order(OrderStatus.PREPARING, number='ORD-OPEN')
        blocked = self.client.patch(reverse('admin-user-detail', args=[self.branch.user.id]), {'is_active': False, 'display_name': 'ไม่ควรเปลี่ยน'}, format='json')
        self.assertEqual(blocked.status_code, status.HTTP_409_CONFLICT)
        self.branch.user.refresh_from_db()
        self.assertTrue(self.branch.user.is_active)
        self.assertEqual(self.branch.user.display_name, 'ครัว')  # rollback ทั้งคำขอ

    def test_password_reset_not_for_admin(self):
        url = reverse('admin-user-password', args=[self.customer.id])
        ok = self.client.post(url, {'password': 'Cust-Pass-2026-ok', 'password_confirm': 'Cust-Pass-2026-ok'}, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.check_password('Cust-Pass-2026-ok'))
        admin = self.client.post(reverse('admin-user-password', args=[self.admin.id]), {'password': 'x' * 14, 'password_confirm': 'x' * 14}, format='json')
        self.assertEqual(admin.status_code, status.HTTP_409_CONFLICT)


class DataTablesAndProofTests(ConsoleBase):
    def test_tables_list_and_device_token_deactivate(self):
        Notification.objects.create(user=self.customer, title='ทดสอบ', body='ข้อความ')
        token = DeviceToken.objects.create(user=self.customer, fcm_token='a' * 40)
        tables = {row['key']: row for row in self.client.get(reverse('admin-data-tables')).data['data']}
        self.assertEqual(tables['notifications']['count'], 1)

        rows = self.client.get(reverse('admin-data-table', args=['device_tokens'])).data
        self.assertEqual(rows['data'][0]['actions'], ['deactivate'])
        self.assertNotIn('a' * 40, json.dumps(rows['data'], default=str))  # token ถูกปิดบัง

        response = self.client.post(reverse('admin-data-action', args=['device_tokens', token.id, 'deactivate']))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token.refresh_from_db()
        self.assertFalse(token.is_active)
        self.assertTrue(AdminAuditLog.objects.filter(action='device_token.deactivate').exists())

        not_allowed = self.client.post(reverse('admin-data-action', args=['notifications', Notification.objects.get().id, 'deactivate']))
        self.assertEqual(not_allowed.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse('admin-data-table', args=['nope'])).status_code, status.HTTP_404_NOT_FOUND)

    def test_delivery_proof_signed_link(self):
        rider_user = User.objects.create(display_name='ไรเดอร์', email='r@example.com', role=UserRole.RIDER)
        RiderProfile.objects.create(user=rider_user, vehicle_plate='กข 1')
        order = self.make_order()
        proof = DeliveryProof.objects.create(order=order, rider=rider_user, proof_image=png('proof.png'), recipient_confirmed=True)

        rows = self.client.get(reverse('admin-data-table', args=['delivery_proofs'])).data['data']
        url = rows[0]['proof_url']
        self.assertIsNone(rows[0]['signature_url'])

        anonymous = APIClient()
        image = anonymous.get(url)
        self.assertEqual(image.status_code, status.HTTP_200_OK)
        self.assertEqual(image['Content-Type'], 'image/png')

        tampered = url.replace('/proof/', '/signature/')
        self.assertEqual(anonymous.get(tampered).status_code, status.HTTP_403_FORBIDDEN)
        other = anonymous.get(url.rsplit('/', 2)[0] + '/bogus-token/')
        self.assertEqual(other.status_code, status.HTTP_403_FORBIDDEN)

        detail = self.client.get(reverse('admin-order-detail', args=[order.id])).data['data']
        self.assertTrue(detail['delivery_proof']['proof_url'])

    def test_data_endpoints_admin_only(self):
        self.client.force_authenticate(self.customer)
        for name, args in (('admin-data-tables', []), ('admin-data-table', ['notifications']), ('admin-dashboard', []), ('admin-user-list', [])):
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, status.HTTP_403_FORBIDDEN, name)


class DashboardTests(ConsoleBase):
    def test_dashboard_numbers(self):
        item = MenuItem.objects.create(merchant=self.branch, name='กะเพรา', price=Decimal('50'))
        self.make_order(OrderStatus.COMPLETED, number='D-1', item=item)
        self.make_order(OrderStatus.PREPARING, number='D-2', item=item)
        self.make_order(OrderStatus.CANCELLED, number='D-3')
        self.make_order(OrderStatus.PENDING_PAYMENT, number='D-4', paid=False)
        rider_user = User.objects.create(display_name='ไรเดอร์', email='r@example.com', role=UserRole.RIDER)
        RiderProfile.objects.create(user=rider_user, vehicle_plate='1', is_online=True)

        data = self.client.get(reverse('admin-dashboard')).data['data']
        self.assertEqual(data['today']['revenue'], '260.00')  # D-1 + D-2 (ยกเลิกไม่นับ, ยังไม่จ่ายไม่นับ)
        self.assertEqual(data['today']['paid_orders'], 2)
        self.assertEqual(data['today']['cancelled_orders'], 1)
        self.assertEqual(data['open_orders']['total'], 2)  # PREPARING + PENDING_PAYMENT
        self.assertEqual(len(data['sales_last_7_days']), 7)
        self.assertEqual(data['sales_last_7_days'][-1]['revenue'], '260.00')
        self.assertEqual(data['top_items'][0], {'name': 'กะเพรา', 'quantity': 4})
        self.assertEqual(data['riders'][0]['is_online'], True)
        self.assertEqual(data['branches'], {'total': 1, 'open': 0})
