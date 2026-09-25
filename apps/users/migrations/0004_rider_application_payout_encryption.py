from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('users', '0003_role_change_requests')]

    operations = [
        migrations.AddField(model_name='riderapplication', name='bank_account_name_encrypted', field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name='riderapplication', name='bank_account_number_encrypted', field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name='riderapplication', name='bank_name_encrypted', field=models.TextField(blank=True, null=True)),
    ]
