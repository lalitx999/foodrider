from decimal import Decimal
from unittest.mock import patch

from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.backoffice.models import AdminAuditLog
from apps.merchants.models import Merchant
from apps.orders.models import Order, OrderStatus, OrderStatusLog
from apps.riders.models import RiderProfile
from apps.users.models import CustomerProfile, User, UserRole


def _merchant(email='kitchen@example.com', name='ร้านทดสอบ'):
    user = User.objects.create(display_name=name, email=email, role=UserRole.MERCHANT)
    return Merchant.objects.create(
        user=user, name=name, image_url='https://example.com/s.png', phone_number='0811111111', address='ถนนทดสอบ',
        latitude=Decimal('12.92'), longitude=Decimal('100.88'), location=Point(100.88, 12.92, srid=4326),
        is_open=True, bank_account_name='-', bank_account_number='-', bank_name='-',
    )


def _rider(email='rider@example.com', name='ไรเดอร์ A', online=True, active=True):
    user = User.objects.create(display_name=name, email=email, role=UserRole.RIDER, is_active=active, phone_number='0822222222')
    return RiderProfile.objects.create(user=user, vehicle_plate='กข 1', is_online=online)


class AdminOrderTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create(display_name='เจ้าของ', email='owner@example.com', role=UserRole.ADMIN)
        self.client.force_authenticate(self.admin)
        self.customer = User.objects.create(display_name='ลูกค้า สมหญิง', email='c@example.com', role=UserRole.CUSTOMER, phone_number='0899999999')
        CustomerProfile.objects.create(user=self.customer, default_delivery_address='บ้าน')
        self.merchant = _merchant()
        self.notify = patch('apps.backoffice.order_actions.create_and_send_notification').start()
        self.addCleanup(patch.stopall)
        self._n = 0

    def order(self, order_status=OrderStatus.PAID, rider=None, **extra):
        self._n += 1
        return Order.objects.create(
            order_number=f'ORD-ADM-{self._n:04d}', customer=self.customer, merchant=self.merchant, rider=rider,
            status=order_status, subtotal=Decimal('100.00'), delivery_fee=Decimal('30.00'), total_amount=Decimal('130.00'),
            delivery_address='99 หมู่บ้านทดสอบ', delivery_latitude=Decimal('12.93'), delivery_longitude=Decimal('100.89'),
            delivery_location=Point(100.89, 12.93, srid=4326), delivery_distance_km=Decimal('2.00'),
            rider_delivery_fee=Decimal('25.00'), platform_fee=Decimal('15.00'), **extra,
        )

    # ---------- สิทธิ์ ----------

    def test_non_admin_cannot_use_order_endpoints(self):
        order = self.order()
        self.client.force_authenticate(self.merchant.user)
        self.assertEqual(self.client.get(reverse('admin-order-list')).status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.post(reverse('admin-order-cancel', args=[order.id]), {'reason': 'ทดสอบยกเลิก'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Order.objects.get(pk=order.pk).status, OrderStatus.PAID)

    # ---------- รายการ / รายละเอียด ----------

    def test_list_filters_search_and_counts(self):
        self.order(OrderStatus.PAID)
        self.order(OrderStatus.PAID)
        done = self.order(OrderStatus.COMPLETED)
        response = self.client.get(reverse('admin-order-list'), {'status': 'COMPLETED'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row['id'] for row in response.data['data']], [str(done.id)])
        self.assertEqual(response.data['meta']['status_counts']['PAID'], 2)
        self.assertEqual(response.data['meta']['status_counts']['COMPLETED'], 1)

        by_phone = self.client.get(reverse('admin-order-list'), {'q': '0899999999'})
        self.assertEqual(by_phone.data['meta']['total'], 3)
        by_number = self.client.get(reverse('admin-order-list'), {'q': done.order_number})
        self.assertEqual(by_number.data['meta']['total'], 1)

        bad = self.client.get(reverse('admin-order-list'), {'status': 'NOPE'})
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

    def test_detail_has_money_history_and_actions(self):
        order = self.order(OrderStatus.PREPARING)
        response = self.client.get(reverse('admin-order-detail', args=[order.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(data['money']['total_amount'], '130.00')
        self.assertEqual(data['customer']['phone'], '0899999999')
        self.assertEqual(data['actions']['next_status'], OrderStatus.READY_FOR_PICKUP)
        self.assertTrue(data['actions']['can_cancel'])
        self.assertTrue(data['actions']['refund_needed_if_cancelled'])

    # ---------- ยกเลิก ----------

    def test_cancel_requires_reason_and_writes_audit(self):
        order = self.order(OrderStatus.PAID)
        url = reverse('admin-order-cancel', args=[order.id])
        self.assertEqual(self.client.post(url, {'reason': 'x'}, format='json').status_code, status.HTTP_400_BAD_REQUEST)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, {'reason': 'ลูกค้าโทรมายกเลิก'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['data']['refund_needed'])
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(order.cancelled_by, self.admin)

        log = AdminAuditLog.objects.get(action='order.cancel')
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.target_id, str(order.id))
        self.assertEqual(log.changes['status'], {'from': 'PAID', 'to': 'CANCELLED'})
        self.assertIn('ต้องคืนเงิน', log.note)
        self.assertTrue(OrderStatusLog.objects.filter(order=order, to_status=OrderStatus.CANCELLED, role='ADMIN').exists())
        self.assertGreaterEqual(self.notify.call_count, 2)  # ลูกค้า + ร้าน

    def test_unpaid_cancel_needs_no_refund_and_closed_orders_cannot_cancel(self):
        unpaid = self.order(OrderStatus.PENDING_PAYMENT)
        response = self.client.post(reverse('admin-order-cancel', args=[unpaid.id]), {'reason': 'ไม่ได้ชำระเงิน'}, format='json')
        self.assertFalse(response.data['data']['refund_needed'])

        done = self.order(OrderStatus.COMPLETED)
        response = self.client.post(reverse('admin-order-cancel', args=[done.id]), {'reason': 'ลองยกเลิกงานที่จบแล้ว'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Order.objects.get(pk=done.pk).status, OrderStatus.COMPLETED)

    # ---------- เลื่อนสถานะ ----------

    def test_advance_one_step_only(self):
        order = self.order(OrderStatus.PAID)
        url = reverse('admin-order-status', args=[order.id])
        skip = self.client.post(url, {'to_status': 'READY_FOR_PICKUP'}, format='json')
        self.assertEqual(skip.status_code, status.HTTP_409_CONFLICT)

        ok = self.client.post(url, {'to_status': 'PREPARING'}, format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)
        self.assertEqual(Order.objects.get(pk=order.pk).status, OrderStatus.PREPARING)
        self.assertTrue(AdminAuditLog.objects.filter(action='order.status', target_id=str(order.id)).exists())

    def test_admin_cannot_mark_paid_without_slip(self):
        order = self.order(OrderStatus.PENDING_PAYMENT)
        response = self.client.post(reverse('admin-order-status', args=[order.id]), {'to_status': 'PAID'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(Order.objects.get(pk=order.pk).status, OrderStatus.PENDING_PAYMENT)

    def test_complete_for_rider_needs_reason_and_pays_rider(self):
        profile = _rider()
        order = self.order(OrderStatus.DELIVERING, rider=profile.user)
        url = reverse('admin-order-status', args=[order.id])
        self.assertEqual(self.client.post(url, {'to_status': 'COMPLETED'}, format='json').status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(url, {'to_status': 'COMPLETED', 'note': 'ไรเดอร์แบตหมด ส่งถึงแล้ว'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        profile.refresh_from_db()
        self.assertEqual(profile.wallet_balance, Decimal('25.00'))
        log = AdminAuditLog.objects.get(action='order.status')
        self.assertEqual(log.changes['rider_wallet'], {'from': '0.00', 'to': '25.00'})

    # ---------- ไรเดอร์ ----------

    def test_assign_rider_moves_to_delivering(self):
        profile = _rider()
        order = self.order(OrderStatus.READY_FOR_PICKUP)
        response = self.client.post(reverse('admin-order-assign-rider', args=[order.id]), {'rider_id': str(profile.id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DELIVERING)
        self.assertEqual(order.rider, profile.user)
        self.assertTrue(AdminAuditLog.objects.filter(action='order.assign_rider').exists())

    def test_reassign_rider_needs_reason_and_keeps_status(self):
        first, second = _rider(), _rider(email='r2@example.com', name='ไรเดอร์ B')
        order = self.order(OrderStatus.DELIVERING, rider=first.user)
        url = reverse('admin-order-assign-rider', args=[order.id])
        no_reason = self.client.post(url, {'rider_id': str(second.id)}, format='json')
        self.assertEqual(no_reason.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(url, {'rider_id': str(second.id), 'note': 'รถเสียกลางทาง'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        order.refresh_from_db()
        self.assertEqual(order.rider, second.user)
        self.assertEqual(order.status, OrderStatus.DELIVERING)
        self.assertTrue(OrderStatusLog.objects.filter(order=order, note__contains='เปลี่ยนไรเดอร์').exists())

    def test_cannot_assign_inactive_or_unknown_rider_or_wrong_status(self):
        inactive = _rider(email='off@example.com', active=False)
        order = self.order(OrderStatus.READY_FOR_PICKUP)
        url = reverse('admin-order-assign-rider', args=[order.id])
        self.assertEqual(self.client.post(url, {'rider_id': str(inactive.id)}, format='json').status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            self.client.post(url, {'rider_id': '00000000-0000-0000-0000-000000000000'}, format='json').status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(self.client.post(url, {'rider_id': 'not-a-uuid'}, format='json').status_code, status.HTTP_400_BAD_REQUEST)

        paid = self.order(OrderStatus.PAID)
        response = self.client.post(reverse('admin-order-assign-rider', args=[paid.id]), {'rider_id': str(_rider(email='r3@example.com').id)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)


class AuditLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create(display_name='เจ้าของ', email='owner@example.com', role=UserRole.ADMIN)
        self.client.force_authenticate(self.admin)

    def test_staff_actions_are_audited_without_secrets(self):
        password = 'Branch-Pass-2026!'
        self.client.post(reverse('admin-rider-list'), {
            'display_name': 'น้อง', 'email': 'rider@example.com', 'phone_number': '0811111111',
            'vehicle_plate': 'กข 1', 'password': password, 'password_confirm': password,
        }, format='json')
        profile = RiderProfile.objects.get()
        self.client.patch(reverse('admin-rider-detail', args=[profile.id]), {'is_active': False}, format='json')
        self.client.post(reverse('admin-rider-password', args=[profile.id]), {'password': 'New-Pass-2026-abc', 'password_confirm': 'New-Pass-2026-abc'}, format='json')

        actions = list(AdminAuditLog.objects.order_by('created_at').values_list('action', flat=True))
        self.assertEqual(actions, ['rider.create', 'rider.deactivate', 'rider.password_reset'])
        for entry in AdminAuditLog.objects.all():
            self.assertNotIn(password, str(entry.changes) + entry.note)
            self.assertNotIn('New-Pass-2026-abc', str(entry.changes) + entry.note)

    def test_audit_list_filters_and_is_admin_only(self):
        AdminAuditLog.objects.create(actor=self.admin, actor_label='a', action='order.cancel', target_type='order', target_id='1', target_label='ORD-1')
        AdminAuditLog.objects.create(actor=self.admin, actor_label='a', action='branch.create', target_type='branch', target_id='2', target_label='สาขา')
        response = self.client.get(reverse('admin-audit-log-list'), {'target_type': 'order'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['data']), 1)
        self.assertEqual(response.data['data'][0]['action_label'], 'ยกเลิกออเดอร์')

        customer = User.objects.create(display_name='c', email='c@example.com', role=UserRole.CUSTOMER)
        self.client.force_authenticate(customer)
        self.assertEqual(self.client.get(reverse('admin-audit-log-list')).status_code, status.HTTP_403_FORBIDDEN)
