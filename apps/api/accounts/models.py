import re
import uuid

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


class OtpChallenge(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        PASSWORD_RESET = "PASSWORD_RESET", "Password reset"

    class Channel(models.TextChoices):
        WHATSAPP = "WHATSAPP", "WhatsApp"
        EMAIL = "EMAIL", "Email"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="otp_challenges")
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    code_hash = models.CharField(max_length=64)
    destination_masked = models.CharField(max_length=120)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    # Set when the challenge stops being usable, whether it was redeemed or
    # superseded by a newer code for the same user and purpose.
    consumed_at = models.DateTimeField(null=True, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "purpose", "-created_at"])]
