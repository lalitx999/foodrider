import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('notifications', '0002_processedlinewebhookevent')]

    operations = [
        migrations.DeleteModel(name='ProcessedLineWebhookEvent'),
        migrations.AlterField(model_name='devicetoken', name='fcm_token', field=models.CharField(db_index=True, max_length=4096, unique=True)),
        migrations.AddField(model_name='devicetoken', name='is_active', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='devicetoken', name='last_seen_at', field=models.DateTimeField(auto_now=True)),
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('body', models.TextField()),
                ('data', models.JSONField(blank=True, default=dict)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'notifications', 'ordering': ['-created_at']},
        ),
    ]
