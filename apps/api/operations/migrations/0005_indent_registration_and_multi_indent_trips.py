from django.db import migrations, models
import django.db.models.deletion


def backfill_trip_indent_links(apps, schema_editor):
    Trip = apps.get_model("operations", "Trip")
    TripIndent = apps.get_model("operations", "TripIndent")
    links = [
        TripIndent(trip_id=trip.pk, indent_id=trip.indent_id, sequence=1, is_primary=True)
        for trip in Trip.objects.all().only("id", "indent_id")
    ]
    TripIndent.objects.bulk_create(links, ignore_conflicts=True)


def backfill_challan_fields(apps, schema_editor):
    Indent = apps.get_model("operations", "Indent")
    for indent in Indent.objects.all().iterator():
        indent.challan_no = indent.indent_no
        indent.challan_datetime = None
        indent.save(update_fields=["challan_no", "challan_datetime"])


class Migration(migrations.Migration):
    dependencies = [("operations", "0004_document_approval_packet")]

    operations = [
        migrations.AddField(
            model_name="indent",
            name="challan_no",
            field=models.CharField(blank=True, db_index=True, max_length=50),
        ),
        migrations.AddField(
            model_name="indent",
            name="challan_datetime",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="indent",
            name="default_quantity",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="indent",
            name="destination_state",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="indent",
            name="item",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="indent",
            name="pin_code",
            field=models.CharField(blank=True, max_length=12),
        ),
        migrations.AddField(
            model_name="indent",
            name="quantity_ltrs",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="indent",
            name="ship_to_address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="indent",
            name="ship_to_party_code",
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name="indent",
            name="ship_to_party_name",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.CreateModel(
            name="TripIndent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sequence", models.PositiveSmallIntegerField(default=1)),
                ("is_primary", models.BooleanField(default=False)),
                ("indent", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="trip_links", to="operations.indent")),
                ("trip", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="indent_links", to="operations.trip")),
            ],
            options={"ordering": ["sequence", "id"]},
        ),
        migrations.AddField(
            model_name="trip",
            name="indents",
            field=models.ManyToManyField(related_name="assigned_trips", through="operations.TripIndent", to="operations.indent"),
        ),
        migrations.AddIndex(
            model_name="indent",
            index=models.Index(fields=["indent_date", "status"], name="operations__indent__bb0676_idx"),
        ),
        migrations.AddIndex(
            model_name="indent",
            index=models.Index(fields=["ship_to_party_code"], name="operations__ship_to_88f378_idx"),
        ),
        migrations.AddIndex(
            model_name="tripindent",
            index=models.Index(fields=["indent", "trip"], name="operations__indent__211e80_idx"),
        ),
        migrations.AddConstraint(
            model_name="tripindent",
            constraint=models.UniqueConstraint(fields=("trip", "indent"), name="unique_trip_indent_assignment"),
        ),
        migrations.AddConstraint(
            model_name="tripindent",
            constraint=models.UniqueConstraint(condition=models.Q(("is_primary", True)), fields=("trip",), name="one_primary_indent_per_trip"),
        ),
        migrations.RunPython(backfill_trip_indent_links, migrations.RunPython.noop),
        migrations.RunPython(backfill_challan_fields, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="indent",
            constraint=models.UniqueConstraint(condition=models.Q(("challan_no", ""), _negated=True), fields=("client", "challan_no"), name="unique_client_challan_no"),
        ),
    ]
