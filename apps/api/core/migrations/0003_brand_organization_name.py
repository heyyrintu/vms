from django.db import migrations, models


def rename_default_organization(apps, schema_editor):
    OrganizationSettings = apps.get_model("core", "OrganizationSettings")
    OrganizationSettings.objects.filter(name="NPL Transport Operations").update(
        name="Drona Logitech Operations"
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_organizationsettings_audit_retention_days_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organizationsettings",
            name="name",
            field=models.CharField(default="Drona Logitech Operations", max_length=150),
        ),
        migrations.RunPython(rename_default_organization, migrations.RunPython.noop),
    ]
