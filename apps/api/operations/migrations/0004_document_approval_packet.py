from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("operations", "0003_alter_document_kind")]

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
                    ("APPROVAL_PACKET", "Approval packet"),
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
