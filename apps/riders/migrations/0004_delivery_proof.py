import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('orders', '0002_initial'), ('riders', '0003_rider_payout_encryption'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='DeliveryProof', fields=[('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),('proof_image', models.ImageField(upload_to='delivery-proofs/images/')),('signature_image', models.ImageField(blank=True, null=True, upload_to='delivery-proofs/signatures/')),('recipient_confirmed', models.BooleanField(default=False)),('created_at', models.DateTimeField(auto_now_add=True)),('order', models.OneToOneField(on_delete=django.db.models.deletion.RESTRICT, related_name='delivery_proof', to='orders.order')),('rider', models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, related_name='delivery_proofs', to=settings.AUTH_USER_MODEL))], options={'db_table':'delivery_proofs'})]
