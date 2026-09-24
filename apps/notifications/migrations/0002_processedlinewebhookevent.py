# Generated manually for Module 22. Apply with: python manage.py migrate

import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProcessedLineWebhookEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('webhook_event_id', models.CharField(db_index=True, max_length=128, unique=True)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'processed_line_webhook_events',
                'ordering': ['-received_at'],
            },
        ),
    ]
