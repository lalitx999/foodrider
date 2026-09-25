from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('users', '0006_add_email_identity')]
    operations = [migrations.RemoveField(model_name='user', name='line_user_id')]
