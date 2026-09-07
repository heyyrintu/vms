import re

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.db.models.functions import Lower


class User(AbstractUser):
    class Role(models.TextChoices):
        OPERATIONS = "OPERATIONS", "Operations"
        APPROVER = "APPROVER", "Approver"
        FINANCE = "FINANCE", "Finance"
        MANAGEMENT = "MANAGEMENT", "Management"
        TRANSPORTER = "TRANSPORTER", "Transporter"
        ADMIN = "ADMIN", "Admin"

    class Meta(AbstractUser.Meta):
        constraints = [
            UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="accounts_user_unique_email_ci",
            ),
            UniqueConstraint(
                fields=["whatsapp_phone"],
                condition=~Q(whatsapp_phone=""),
                name="accounts_user_unique_whatsapp_phone",
            ),
        ]

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OPERATIONS)
    vendor = models.ForeignKey(
        "operations.Vendor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="portal_users",
    )
    mfa_secret_encrypted = models.TextField(blank=True)
    mfa_enabled = models.BooleanField(default=False)
    whatsapp_phone = models.CharField(max_length=15, blank=True)

    def clean(self):
        super().clean()
        if self.role == self.Role.TRANSPORTER and not self.vendor_id:
            raise ValidationError({"vendor": "Transporter users must be linked to a vendor."})
        normalized = re.sub(r"[\s()+-]", "", self.whatsapp_phone or "")
        if normalized and (
            not normalized.isdigit()
            or not 8 <= len(normalized) <= 15
            or normalized[0] == "0"
        ):
            raise ValidationError(
                {
                    "whatsapp_phone": (
                        "Enter an international WhatsApp number using 8-15 digits, "
                        "for example 919876543210."
                    )
                }
            )
        self.whatsapp_phone = normalized
