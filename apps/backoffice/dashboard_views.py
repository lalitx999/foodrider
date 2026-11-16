"""
หลังบ้าน: แดชบอร์ดภาพรวม (Module 32 เฟส B · B7)

ตัวเลขทั้งหมดคิดตามเวลาไทย (TIME_ZONE = Asia/Bangkok)
- ยอดขาย = ออเดอร์ที่ชำระเงินแล้วและไม่ถูกยกเลิก นับตามวันที่ชำระ (paid_at)
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.backoffice.order_actions import STATUS_LABELS
from apps.merchants.models import BankChangeStatus, Merchant, MerchantBankChangeRequest
from apps.orders.models import Order, OrderStatus
from apps.payments.models import SlipStatus, SlipTransaction
from apps.riders.live_location import get_live_location
from apps.riders.models import RiderProfile
from apps.users.permissions import IsAdminRole

SALES_DAYS = 7
OPEN_STATUSES = [OrderStatus.PENDING_PAYMENT, OrderStatus.PAID, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP, OrderStatus.DELIVERING]
# ค้างสถานะเดิมนานกว่านี้ (นาที) = ต้องรีบดู
STUCK_MINUTES = 30


def _money(value) -> str:
    return str((value or Decimal('0')).quantize(Decimal('0.01')))


class AdminDashboardView(APIView):
    """GET /api/admin/v1/dashboard/"""

    permission_classes = [IsAdminRole]
    throttle_scope = 'admin'

    def get(self, request):
        now = timezone.localtime()
        today = now.date()
        start = today - timedelta(days=SALES_DAYS - 1)

        sold = Order.objects.filter(paid_at__isnull=False).exclude(status=OrderStatus.CANCELLED)
        today_sold = sold.filter(paid_at__date=today).aggregate(
            revenue=Sum('total_amount'), orders=Count('id'), delivery=Sum('delivery_fee'), rider=Sum('rider_delivery_fee'),
        )
        today_created = Order.objects.filter(created_at__date=today).aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status=OrderStatus.COMPLETED)),
            cancelled=Count('id', filter=Q(status=OrderStatus.CANCELLED)),
        )

        daily = {
            row['day']: row
            for row in sold.filter(paid_at__date__gte=start)
            .annotate(day=TruncDate('paid_at'))
            .values('day')
            .annotate(revenue=Sum('total_amount'), orders=Count('id'))
        }
        sales = []
        for offset in range(SALES_DAYS):
            day = start + timedelta(days=offset)
            row = daily.get(day, {})
            sales.append({'date': day.isoformat(), 'revenue': _money(row.get('revenue')), 'orders': row.get('orders', 0)})

        open_counts = {row['status']: row['n'] for row in Order.objects.filter(status__in=OPEN_STATUSES).values('status').annotate(n=Count('id'))}
        stuck = Order.objects.filter(status__in=OPEN_STATUSES, updated_at__lt=now - timedelta(minutes=STUCK_MINUTES)).count()

        top_items = list(
            Order.objects.filter(paid_at__date__gte=start)
            .exclude(status=OrderStatus.CANCELLED)
            .values('items__item_name')
            .annotate(quantity=Sum('items__quantity'))
            .exclude(items__item_name__isnull=True)
            .order_by('-quantity')[:5]
        )

        riders = []
        for profile in RiderProfile.objects.select_related('user').filter(user__is_active=True).order_by('-is_online', 'user__display_name'):
            live = get_live_location(profile.user_id) if profile.is_online else None
            riders.append({
                'id': str(profile.id),
                'name': profile.user.display_name,
                'is_online': profile.is_online,
                'active_jobs': Order.objects.filter(rider=profile.user, status=OrderStatus.DELIVERING).count(),
                'last_location_at': live.updated_at if live else None,
            })

        branches = Merchant.objects.filter(user__is_active=True)
        return Response({
            'success': True,
            'data': {
                'generated_at': now,
                'today': {
                    'revenue': _money(today_sold['revenue']),
                    'paid_orders': today_sold['orders'] or 0,
                    'delivery_fees': _money(today_sold['delivery']),
                    'rider_fees': _money(today_sold['rider']),
                    'average_order': _money((today_sold['revenue'] or Decimal('0')) / today_sold['orders']) if today_sold['orders'] else '0.00',
                    'created_orders': today_created['total'] or 0,
                    'completed_orders': today_created['completed'] or 0,
                    'cancelled_orders': today_created['cancelled'] or 0,
                },
                'sales_last_7_days': sales,
                'open_orders': {
                    'total': sum(open_counts.values()),
                    'stuck': stuck,
                    'stuck_minutes': STUCK_MINUTES,
                    'by_status': [{'status': value, 'label': STATUS_LABELS[value], 'count': open_counts.get(value, 0)} for value in OPEN_STATUSES],
                },
                'top_items': [{'name': row['items__item_name'], 'quantity': row['quantity']} for row in top_items],
                'riders': riders,
                'branches': {'total': branches.count(), 'open': branches.filter(is_open=True).count()},
                'pending': {
                    'slips': SlipTransaction.objects.filter(status=SlipStatus.PENDING).count(),
                    'bank_changes': MerchantBankChangeRequest.objects.filter(status=BankChangeStatus.PENDING).count(),
                },
            },
        })
