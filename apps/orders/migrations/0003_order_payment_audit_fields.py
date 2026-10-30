import django.db.models.deletion
import uuid
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """P0-02/P0-03: ฟิลด์เงิน/เวลาชำระเงิน + audit log ของสถานะออเดอร์"""

    dependencies = [
        ('orders', '0002_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='platform_delivery_fee',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('0.00'), max_digits=10
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='cancelled_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='cancelled_orders',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='order',
            name='paid_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='OrderStatusLog',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('from_status', models.CharField(blank=True, choices=[('PENDING_PAYMENT', 'Pending Payment'), ('PAID', 'Paid'), ('PREPARING', 'Preparing'), ('READY_FOR_PICKUP', 'Ready for Pickup'), ('DELIVERING', 'Delivering'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled')], max_length=30, null=True)),
                ('to_status', models.CharField(choices=[('PENDING_PAYMENT', 'Pending Payment'), ('PAID', 'Paid'), ('PREPARING', 'Preparing'), ('READY_FOR_PICKUP', 'Ready for Pickup'), ('DELIVERING', 'Delivering'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled')], db_index=True, max_length=30)),
                ('role', models.CharField(blank=True, help_text='SYSTEM / CUSTOMER / MERCHANT / RIDER / ADMIN', max_length=20)),
                ('note', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='order_status_logs', to=settings.AUTH_USER_MODEL)),
                ('order', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='status_logs', to='orders.order')),
            ],
            options={
                'db_table': 'order_status_logs',
                'ordering': ['-created_at'],
            },
        ),
    ]
