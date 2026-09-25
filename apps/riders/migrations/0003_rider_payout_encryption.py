from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('riders', '0002_initial')]

    operations = [
        migrations.AddField(model_name='riderprofile', name='bank_account_name_encrypted', field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name='riderprofile', name='bank_account_number_encrypted', field=models.TextField(blank=True, null=True)),
        migrations.AddField(model_name='riderprofile', name='bank_name_encrypted', field=models.TextField(blank=True, null=True)),
    ]
