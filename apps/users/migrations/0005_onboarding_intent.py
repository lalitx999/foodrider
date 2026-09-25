from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('users', '0004_rider_application_payout_encryption')]

    operations = [
        migrations.CreateModel(
            name='OnboardingIntent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('selected_role', models.CharField(choices=[('CUSTOMER', 'Customer'), ('MERCHANT', 'Merchant'), ('RIDER', 'Rider')], max_length=20)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('COMPLETED', 'Completed'), ('CANCELLED', 'Cancelled')], db_index=True, default='PENDING', max_length=20)),
                ('selected_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='onboarding_intent', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'onboarding_intents'},
        ),
    ]
