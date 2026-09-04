from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction


class TDSPolicy(models.TextChoices):
    PER_PAYMENT_TAXABLE_AMOUNT = "PER_PAYMENT_TAXABLE_AMOUNT", "Per payment taxable amount"
    FULL_FREIGHT_AT_FIRST_ADVANCE = "FULL_FREIGHT_AT_FIRST_ADVANCE", "Full freight at first advance"
    CUMULATIVE_TRIP_LIABILITY = "CUMULATIVE_TRIP_LIABILITY", "Cumulative trip liability"
    MANUAL_WITH_APPROVAL = "MANUAL_WITH_APPROVAL", "Manual with approval"


class OrganizationSettings(models.Model):
    name = models.CharField(max_length=150, default="Drona Logitech Operations")
    currency = models.CharField(max_length=3, default="INR")
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    default_advance_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("90.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    default_tds_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )
    default_tds_policy = models.CharField(
        max_length=40,
        choices=TDSPolicy.choices,
        default=TDSPolicy.PER_PAYMENT_TAXABLE_AMOUNT,
    )
    allow_self_approval = models.BooleanField(default=False)
    require_payment_proof = models.BooleanField(default=False)
    require_pod_for_settlement = models.BooleanField(default=True)
    require_vendor_invoice_for_settlement = models.BooleanField(default=True)
    comment_edit_window_minutes = models.PositiveSmallIntegerField(default=15)
    audit_retention_days = models.PositiveIntegerField(default=2555)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class NumberSequence(models.Model):
    key = models.CharField(max_length=80, unique=True)
    value = models.PositiveBigIntegerField(default=0)

    @classmethod
    def next(cls, key):
        # Missing rows cannot be locked. Retry the unique-key race that can occur
        # when the first two workers request the same sequence concurrently.
        for _attempt in range(5):
            try:
                with transaction.atomic():
                    sequence = cls.objects.select_for_update().filter(key=key).first()
                    if sequence is None:
                        return cls.objects.create(key=key, value=1).value
                    sequence.value += 1
                    sequence.save(update_fields=["value"])
                    return sequence.value
            except IntegrityError:
                continue
        raise RuntimeError(f"Could not allocate number sequence for {key}")
