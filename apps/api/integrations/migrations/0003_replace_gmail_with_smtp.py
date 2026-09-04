from django.db import migrations, models


def replace_gmail_connection(apps, schema_editor):
    IntegrationConnection = apps.get_model("integrations", "IntegrationConnection")
    IntegrationConnection.objects.filter(provider="GMAIL").update(
        provider="SMTP",
        status="DISCONNECTED",
        account_label="SMTP email",
        encrypted_credentials="",
        configuration={},
        watch_expires_at=None,
        last_error="SMTP credentials must be configured after upgrading from Gmail OAuth.",
    )


def restore_gmail_connection(apps, schema_editor):
    IntegrationConnection = apps.get_model("integrations", "IntegrationConnection")
    IntegrationConnection.objects.filter(provider="SMTP").update(
        provider="GMAIL",
        status="DISCONNECTED",
        account_label="Gmail",
        encrypted_credentials="",
        configuration={},
        watch_expires_at=None,
        last_error="Gmail OAuth credentials must be configured after migration rollback.",
    )


class Migration(migrations.Migration):
    dependencies = [("integrations", "0002_integrationconnection_last_error_and_more")]

    operations = [
        migrations.RunPython(replace_gmail_connection, restore_gmail_connection),
        migrations.AlterField(
            model_name="integrationconnection",
            name="provider",
            field=models.CharField(
                choices=[("SMTP", "SMTP email"), ("WHATSAPP", "WhatsApp")],
                max_length=20,
                unique=True,
            ),
        ),
    ]
