import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('users', '0002_onboarding_applications')]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('UNASSIGNED', 'Unassigned'),
                    ('CUSTOMER', 'Customer'),
                    ('MERCHANT', 'Merchant'),
                    ('RIDER', 'Rider'),
                    ('ADMIN', 'Admin'),
                ],
                db_index=True,
                default='UNASSIGNED',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='merchantapplication',
            name='bank_account_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='merchantapplication',
            name='bank_account_number',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='merchantapplication',
            name='bank_name',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.CreateModel(
            name='RoleChangeRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('current_role', models.CharField(choices=[('UNASSIGNED', 'Unassigned'), ('CUSTOMER', 'Customer'), ('MERCHANT', 'Merchant'), ('RIDER', 'Rider'), ('ADMIN', 'Admin')], max_length=20)),
                ('requested_role', models.CharField(choices=[('MERCHANT', 'Merchant'), ('RIDER', 'Rider')], max_length=20)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('CANCELLED', 'Cancelled')], db_index=True, default='PENDING', max_length=20)),
                ('admin_note', models.TextField(blank=True, null=True)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('merchant_application', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='role_change_request', to='users.merchantapplication')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_role_change_requests', to=settings.AUTH_USER_MODEL)),
                ('rider_application', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='role_change_request', to='users.riderapplication')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='role_change_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'role_change_requests', 'ordering': ['-requested_at']},
        ),
        migrations.AddConstraint(
            model_name='rolechangerequest',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(merchant_application__isnull=False, rider_application__isnull=True)
                    | models.Q(merchant_application__isnull=True, rider_application__isnull=False)
                ),
                name='role_change_request_has_one_application',
            ),
        ),
    ]
