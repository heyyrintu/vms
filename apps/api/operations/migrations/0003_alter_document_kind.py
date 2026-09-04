from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0002_document_scan_detail_document_scan_status_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="document",
            name="kind",
            field=models.CharField(
                choices=[
                    ("POD", "POD"),
                    ("LR", "LR"),
                    ("VENDOR_INVOICE", "Vendor invoice"),
                    ("PAYMENT_PROOF", "Payment proof"),
                    ("AADHAAR", "Aadhaar"),
                    ("PAN", "PAN"),
                    ("DRIVING_LICENSE", "Driving licence"),
                    ("CANCELLED_CHEQUE", "Cancelled cheque"),
                    ("OTHER", "Other"),
                ],
                default="OTHER",
                max_length=30,
            ),
        ),
    ]
