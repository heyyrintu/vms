import re
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.models import NumberSequence, TDSPolicy


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Client(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    active = models.BooleanField(default=True)
    default_branch = models.CharField(max_length=100, blank=True)
    billing_settings = models.JSONField(default=dict, blank=True)

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Vendor(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        HOLD = "HOLD", "On hold"
        INACTIVE = "INACTIVE", "Inactive"

    vendor_code = models.CharField(max_length=30, unique=True)
    legal_name = models.CharField(max_length=180)
    display_name = models.CharField(max_length=150)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    email = models.EmailField(blank=True)
    primary_contact_name = models.CharField(max_length=120, blank=True)
    primary_phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    tax_identifier = models.CharField(max_length=30, blank=True)
    default_tds_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    default_tds_policy = models.CharField(max_length=40, choices=TDSPolicy.choices, blank=True)
    payment_terms = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    blocked_reason = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        self.vendor_code = self.vendor_code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.display_name


class VendorContact(TimeStampedModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    receives_email = models.BooleanField(default=True)
    receives_whatsapp = models.BooleanField(default=False)


class VendorBankAccount(TimeStampedModel):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="bank_accounts")
    bank_name = models.CharField(max_length=120)
    account_holder = models.CharField(max_length=150)
    account_number_encrypted = models.TextField()
    account_last_four = models.CharField(max_length=4)
    ifsc_code = models.CharField(max_length=20)
    active = models.BooleanField(default=True)

    @property
    def masked_account_number(self):
        return f"•••• {self.account_last_four}"


class Vehicle(TimeStampedModel):
    registration_no = models.CharField(max_length=25, unique=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="vehicles")
    vehicle_type = models.CharField(max_length=80)
    capacity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        self.registration_no = re.sub(r"[^A-Za-z0-9]", "", self.registration_no).upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.registration_no


class Driver(TimeStampedModel):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=30)
    vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.PROTECT, related_name="drivers")
    active = models.BooleanField(default=True)


class Indent(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open"
        FULFILLED = "FULFILLED", "Fulfilled"
        CANCELLED = "CANCELLED", "Cancelled"

    indent_no = models.CharField(max_length=50, unique=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="indents")
    indent_date = models.DateField()
    challan_no = models.CharField(max_length=50, blank=True, db_index=True)
    challan_datetime = models.DateTimeField(null=True, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    cost_center = models.CharField(max_length=100, blank=True)
    origin = models.CharField(max_length=150)
    destination = models.CharField(max_length=150)
    ship_to_party_code = models.CharField(max_length=60, blank=True)
    ship_to_party_name = models.CharField(max_length=180, blank=True)
    ship_to_address = models.TextField(blank=True)
    destination_state = models.CharField(max_length=80, blank=True)
    pin_code = models.CharField(max_length=12, blank=True)
    item = models.CharField(max_length=120, blank=True)
    default_quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    quantity_ltrs = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    reporting_datetime = models.DateTimeField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    uom_ltrs = models.CharField(max_length=40, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    total_load = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    required_vehicle_type = models.CharField(max_length=80, blank=True)
    customer_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)

    class Meta:
        indexes = [
            models.Index(fields=["indent_date", "status"]),
            models.Index(fields=["ship_to_party_code"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "challan_no"],
                condition=~models.Q(challan_no=""),
                name="unique_client_challan_no",
            ),
        ]

    def save(self, *args, **kwargs):
        self.indent_no = self.indent_no.strip().upper()
        self.challan_no = self.challan_no.strip().upper()
        self.pin_code = self.pin_code.strip()
        super().save(*args, **kwargs)


class Trip(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        READY = "READY", "Ready"
        ADVANCE_APPROVAL_PENDING = "ADVANCE_APPROVAL_PENDING", "Advance approval pending"
        ADVANCE_APPROVED = "ADVANCE_APPROVED", "Advance approved"
        ADVANCE_PARTIALLY_PAID = "ADVANCE_PARTIALLY_PAID", "Advance partially paid"
        ADVANCE_PAID = "ADVANCE_PAID", "Advance paid"
        DEPLOYED = "DEPLOYED", "Deployed"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        DELIVERED = "DELIVERED", "Delivered"
        SETTLEMENT_PENDING = "SETTLEMENT_PENDING", "Settlement pending"
        SETTLEMENT_APPROVAL_PENDING = "SETTLEMENT_APPROVAL_PENDING", "Settlement approval pending"
        SETTLED = "SETTLED", "Settled"
        CANCELLED = "CANCELLED", "Cancelled"
        CANCELLED_WITH_PAYMENT = "CANCELLED_WITH_PAYMENT", "Cancelled with payment"

    trip_no = models.CharField(max_length=30, unique=True, blank=True)
    indent = models.ForeignKey(Indent, on_delete=models.PROTECT, related_name="trips")
    indents = models.ManyToManyField(Indent, through="TripIndent", related_name="assigned_trips")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="trips")
    origin = models.CharField(max_length=150)
    destination = models.CharField(max_length=150)
    deployment_date = models.DateField()
    expected_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_at = models.DateTimeField(null=True, blank=True)
    uom_ltrs = models.CharField(max_length=40, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    total_load = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="trips")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT, related_name="trips")
    driver = models.ForeignKey(Driver, on_delete=models.PROTECT, related_name="trips")
    vehicle_registration_snapshot = models.CharField(max_length=25)
    vehicle_type_snapshot = models.CharField(max_length=80)
    driver_name_snapshot = models.CharField(max_length=120)
    driver_phone_snapshot = models.CharField(max_length=30)
    vendor_freight_rate = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    advance_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("90.00"))
    client_billing_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=35, choices=Status.choices, default=Status.READY, db_index=True)
    pod_status = models.CharField(max_length=30, default="PENDING")
    settlement_status = models.CharField(max_length=30, default="OPEN")
    branch = models.CharField(max_length=100, blank=True)
    cost_center = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["deployment_date", "status"]),
            models.Index(fields=["vendor", "deployment_date"]),
            models.Index(fields=["vehicle_registration_snapshot"]),
        ]

    def clean(self):
        if self.vehicle_id and self.vendor_id and self.vehicle.vendor_id != self.vendor_id:
            raise ValidationError({"vehicle": "Vehicle must belong to the selected vendor."})
        if self.driver_id and self.driver.vendor_id and self.driver.vendor_id != self.vendor_id:
            raise ValidationError({"driver": "Driver must belong to the selected vendor."})

    def save(self, *args, **kwargs):
        if not self.trip_no:
            year = self.deployment_date.year if self.deployment_date else timezone.localdate().year
            sequence = NumberSequence.next(f"trip:{self.client.code}:{year}")
            self.trip_no = f"{self.client.code}-{year}-{sequence:06d}"
        if self.vehicle_id:
            self.vehicle_registration_snapshot = self.vehicle.registration_no
            self.vehicle_type_snapshot = self.vehicle.vehicle_type
        if self.driver_id:
            self.driver_name_snapshot = self.driver.name
            self.driver_phone_snapshot = self.driver.phone
        self.full_clean()
        super().save(*args, **kwargs)
        TripIndent.objects.filter(trip=self).exclude(indent=self.indent).update(is_primary=False)
        TripIndent.objects.update_or_create(
            trip=self,
            indent=self.indent,
            defaults={"is_primary": True, "sequence": 1},
        )


class TripIndent(TimeStampedModel):
    """Auditable assignment allowing one vehicle trip to carry multiple client indents."""

    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="indent_links")
    indent = models.ForeignKey(Indent, on_delete=models.PROTECT, related_name="trip_links")
    sequence = models.PositiveSmallIntegerField(default=1)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["sequence", "id"]
        constraints = [
            models.UniqueConstraint(fields=["trip", "indent"], name="unique_trip_indent_assignment"),
            models.UniqueConstraint(
                fields=["trip"],
                condition=models.Q(is_primary=True),
                name="one_primary_indent_per_trip",
            ),
        ]
        indexes = [models.Index(fields=["indent", "trip"])]


class TripCharge(TimeStampedModel):
    class ChargeType(models.TextChoices):
        FREIGHT = "FREIGHT", "Freight"
        UNLOADING = "UNLOADING", "Unloading"
        DETENTION = "DETENTION", "Detention"
        LOADING = "LOADING", "Loading"
        TOLL = "TOLL", "Toll"
        OTHER = "OTHER", "Other"
        DEDUCTION = "DEDUCTION", "Deduction"
        REIMBURSEMENT = "REIMBURSEMENT", "Reimbursement"

    class Direction(models.TextChoices):
        ADD = "ADD", "Add"
        DEDUCT = "DEDUCT", "Deduct"

    class Source(models.TextChoices):
        INITIAL = "INITIAL", "Initial"
        FINAL_SETTLEMENT = "FINAL_SETTLEMENT", "Final settlement"
        MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT", "Manual adjustment"

    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="charges")
    charge_type = models.CharField(max_length=20, choices=ChargeType.choices)
    description = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    direction = models.CharField(max_length=10, choices=Direction.choices, default=Direction.ADD)
    advance_eligible = models.BooleanField(default=False)
    tds_eligible = models.BooleanField(default=False)
    source = models.CharField(max_length=25, choices=Source.choices, default=Source.INITIAL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)


class Document(TimeStampedModel):
    class Kind(models.TextChoices):
        POD = "POD", "POD"
        LR = "LR", "LR"
        VENDOR_INVOICE = "VENDOR_INVOICE", "Vendor invoice"
        PAYMENT_PROOF = "PAYMENT_PROOF", "Payment proof"
        APPROVAL_PACKET = "APPROVAL_PACKET", "Approval packet"
        AADHAAR = "AADHAAR", "Aadhaar"
        PAN = "PAN", "PAN"
        DRIVING_LICENSE = "DRIVING_LICENSE", "Driving licence"
        CANCELLED_CHEQUE = "CANCELLED_CHEQUE", "Cancelled cheque"
        OTHER = "OTHER", "Other"

    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=80)
    kind = models.CharField(max_length=30, choices=Kind.choices, default=Kind.OTHER)
    file = models.FileField(upload_to="documents/%Y/%m/")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    scan_status = models.CharField(
        max_length=20,
        choices=[("PENDING", "Pending"), ("CLEAN", "Clean"), ("REJECTED", "Rejected")],
        default="PENDING",
    )
    scan_detail = models.CharField(max_length=240, blank=True)


class TripRecovery(TimeStampedModel):
    class Resolution(models.TextChoices):
        REFUND = "REFUND", "Refund"
        ADJUST_FUTURE = "ADJUST_AGAINST_FUTURE_TRIP", "Adjust against future trip"
        WRITE_OFF = "WRITE_OFF_WITH_APPROVAL", "Write off with approval"
        OTHER = "OTHER", "Other"

    trip = models.OneToOneField(Trip, on_delete=models.PROTECT, related_name="recovery")
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    resolution_method = models.CharField(max_length=40, choices=Resolution.choices)
    reference = models.CharField(max_length=120, blank=True)
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=[("OPEN", "Open"), ("RESOLVED", "Resolved")],
        default="OPEN",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_recoveries")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="resolved_recoveries",
    )
