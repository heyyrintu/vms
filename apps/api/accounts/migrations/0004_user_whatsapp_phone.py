from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_user_mfa_enabled_user_mfa_secret_encrypted")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="whatsapp_phone",
            field=models.CharField(blank=True, max_length=15),
        ),
    ]
