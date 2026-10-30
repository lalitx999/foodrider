import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_review_status(apps, schema_editor):
    """ข้อมูลเดิม: is_verified=True = อนุมัติแล้ว, มิฉะนั้นถือว่าถูกปฏิเสธ (ไม่ปล่อยเป็น PENDING)"""
    SlipTransaction = apps.get_model('payments', 'SlipTransaction')
    SlipTransaction.objects.filter(is_verified=True).update(status='APPROVED', attempt_no=1)
    SlipTransaction.objects.filter(is_verified=False).update(status='REJECTED', attempt_no=1)


class Migration(migrations.Migration):
    """P0-02: review workflow ของสลิป (status/attempt_no/reviewer/reject_reason)"""

    dependencies = [
        ('orders', '0003_order_payment_audit_fields'),
        ('payments', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(
            model_name='sliptransaction',
            old_name='verified_at',
            new_name='created_at',
        ),
        migrations.AlterField(
            model_name='sliptransaction',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterModelOptions(
            name='sliptransaction',
            options={'db_table': 'slip_transactions', 'ordering': ['-created_at']},
        ),
        migrations.AlterField(
            model_name='sliptransaction',
            name='slip_image_url',
            field=models.TextField(
                help_text='relative path เช่น /media/payment-slips/... (ห้ามเก็บ absolute URL)'
            ),
        ),
        migrations.AlterField(
            model_name='sliptransaction',
            name='is_verified',
            field=models.BooleanField(
                default=False, help_text='derived flag: True เฉพาะสถานะ APPROVED'
            ),
        ),
        migrations.AddField(
            model_name='sliptransaction',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Pending review'),
                    ('APPROVED', 'Approved'),
                    ('REJECTED', 'Rejected'),
                    ('SUPERSEDED', 'Superseded'),
                ],
                db_index=True,
                default='PENDING',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='sliptransaction',
            name='attempt_no',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='sliptransaction',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sliptransaction',
            name='reject_reason',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='sliptransaction',
            name='reviewer',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='reviewed_slips',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_review_status, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='sliptransaction',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status', 'PENDING')),
                fields=('order',),
                name='uniq_pending_slip_per_order',
            ),
        ),
    ]
