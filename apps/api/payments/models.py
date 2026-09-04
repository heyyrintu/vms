from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from approvals.models import PaymentApprovalItem
from core.models import NumberSequence
from operations.models import TimeStampedModel, Trip, Vendor, VendorBankAccount


class FinancePaymentTransaction(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PROCESSING = "PROCESSING", "Processing"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REVERSED = "REVERSED", "Reversed"

    payment_no = models.CharField(max_length=30, unique=True, blank=True)
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField()
    bank_account = models.ForeignKey(VendorBankAccount, null=True, blank=True, on_delete=models.PROTECT)
    payment_mode = models.CharField(max_length=30, default="BANK_TRANSFER")
    utr_reference = models.CharField(max_length=100, db_index=True)
    gross_allocated_amount = models.DecimalField(max_digits=16, decimal_places=2)
    tds_amount = models.DecimalField(max_digits=16, decimal_places=2)
    net_paid_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    proof_document = models.ForeignKey("operations.Document", null=True, blank=True, on_delete=models.PROTECT)
    remarks = models.TextField(blank=True)
    reversal_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_payments")
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="paid_payments")
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(gross_allocated_amount__gte=0), name="payment_gross_nonnegative"),
            models.CheckConstraint(condition=models.Q(tds_amount__gte=0), name="payment_tds_nonnegative"),
            models.CheckConstraint(condition=models.Q(net_paid_amount__gte=0), name="payment_net_nonnegative"),
        ]

    def clean(self):
        if self.gross_allocated_amount != self.tds_amount + self.net_paid_amount:
            raise ValidationError("Gross allocation must equal TDS plus net cash paid")
        if self.bank_account_id and self.bank_account.vendor_id != self.vendor_id:
            raise ValidationError({"bank_account": "Bank account must belong to the payment vendor"})
        if self.status == self.Status.PAID and not self.utr_reference.strip():
            raise ValidationError({"utr_reference": "UTR/reference is required for paid transactions"})

    def save(self, *args, **kwargs):
        if self.pk:
            original = FinancePaymentTransaction.objects.get(pk=self.pk)
            protected = (
                "vendor_id",
                "payment_date",
                "bank_account_id",
                "payment_mode",
                "gross_allocated_amount",
                "tds_amount",
                "net_paid_amount",
                "utr_reference",
                "proof_document_id",
                "remarks",
                "created_by_id",
                "paid_by_id",
                "paid_at",
            )
            if original.status == self.Status.PAID and any(getattr(original, field) != getattr(self, field) for field in protected):
                raise ValidationError("Paid transactions are immutable; reverse and replace instead")
            if original.status == self.Status.PAID and self.status not in {
                self.Status.PAID,
                self.Status.REVERSED,
            }:
                raise ValidationError("Paid transactions can only transition to reversed")
            if original.status == self.Status.PAID and self.status == self.Status.REVERSED and not self.reversal_reason.strip():
                raise ValidationError("A reversal reason is required")
            if original.status == self.Status.REVERSED and (
                self.status != self.Status.REVERSED
                or any(getattr(original, field) != getattr(self, field) for field in protected)
                or original.reversal_reason != self.reversal_reason
            ):
                raise ValidationError("Reversed transactions are immutable")
        if not self.payment_no:
            year = self.payment_date.year if self.payment_date else timezone.localdate().year
            self.payment_no = f"PAY-{year}-{NumberSequence.next(f'payment:{year}'):06d}"
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in {self.Status.PAID, self.Status.REVERSED}:
            raise ValidationError("Paid or reversed transactions cannot be deleted")
        return super().delete(*args, **kwargs)


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(FinancePaymentTransaction, on_delete=models.PROTECT, related_name="allocations")
    approval_item = models.ForeignKey(PaymentApprovalItem, on_delete=models.PROTECT, related_name="allocations")
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="payment_allocations")
    gross_amount_allocated = models.DecimalField(max_digits=14, decimal_places=2)
    tds_allocated = models.DecimalField(max_digits=14, decimal_places=2)
    net_cash_allocated = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["payment", "approval_item"], name="unique_payment_approval_allocation"),
            models.CheckConstraint(condition=models.Q(gross_amount_allocated__gte=0), name="allocation_gross_nonnegative"),
            models.CheckConstraint(condition=models.Q(tds_allocated__gte=0), name="allocation_tds_nonnegative"),
            models.CheckConstraint(condition=models.Q(net_cash_allocated__gte=0), name="allocation_net_nonnegative"),
        ]

    def clean(self):
        if self.payment.vendor_id != self.approval_item.vendor_id:
            raise ValidationError("Allocation vendor must match payment vendor")
        if self.trip_id != self.approval_item.trip_id:
            raise ValidationError("Allocation trip must match approval item trip")
        if self.gross_amount_allocated != self.tds_allocated + self.net_cash_allocated:
            raise ValidationError("Gross allocation must equal TDS plus net cash allocation")

    def save(self, *args, **kwargs):
        locked = {FinancePaymentTransaction.Status.PAID, FinancePaymentTransaction.Status.REVERSED}
        if not self.pk and self.payment.status in locked:
            raise ValidationError("Allocations may only be created while a payment is processing")
        if self.pk:
            original = PaymentAllocation.objects.select_related("payment").get(pk=self.pk)
            fields = (
                "payment_id",
                "approval_item_id",
                "trip_id",
                "gross_amount_allocated",
                "tds_allocated",
                "net_cash_allocated",
            )
            if original.payment.status in locked and any(
                getattr(original, field) != getattr(self, field) for field in fields
            ):
                raise ValidationError("Posted payment allocations are immutable")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.payment.status in {
            FinancePaymentTransaction.Status.PAID,
            FinancePaymentTransaction.Status.REVERSED,
        }:
            raise ValidationError("Posted payment allocations cannot be deleted")
        return super().delete(*args, **kwargs)


class TDSEntry(models.Model):
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="tds_entries")
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="tds_entries")
    payment = models.ForeignKey(FinancePaymentTransaction, on_delete=models.PROTECT, related_name="tds_entries")
    taxable_base = models.DecimalField(max_digits=14, decimal_places=2)
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    tds_amount = models.DecimalField(max_digits=14, decimal_places=2)
    policy_snapshot = models.CharField(max_length=40)
    deduction_date = models.DateField()
    status = models.CharField(max_length=20, default="POSTED")
    finance_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["payment", "trip"], name="unique_payment_trip_tds_entry")]

    def save(self, *args, **kwargs):
        locked = {FinancePaymentTransaction.Status.PAID, FinancePaymentTransaction.Status.REVERSED}
        if not self.pk and self.payment.status in locked:
            raise ValidationError("TDS entries may only be created while a payment is processing")
        if self.pk:
            original = TDSEntry.objects.select_related("payment").get(pk=self.pk)
            fields = (
                "vendor_id",
                "trip_id",
                "payment_id",
                "taxable_base",
                "rate",
                "tds_amount",
                "policy_snapshot",
                "deduction_date",
                "finance_reference",
            )
            if original.payment.status in locked and any(
                getattr(original, field) != getattr(self, field) for field in fields
            ):
                raise ValidationError("Posted TDS entries are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.payment.status in {
            FinancePaymentTransaction.Status.PAID,
            FinancePaymentTransaction.Status.REVERSED,
        }:
            raise ValidationError("Posted TDS entries cannot be deleted")
        return super().delete(*args, **kwargs)


class FinalTripSettlement(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        APPROVAL_PENDING = "APPROVAL_PENDING", "Approval pending"
        APPROVED = "APPROVED", "Approved"
        SETTLED = "SETTLED", "Settled"

    trip = models.OneToOneField(Trip, on_delete=models.PROTECT, related_name="final_settlement")
    final_freight = models.DecimalField(max_digits=14, decimal_places=2)
    additive_charges = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vendor_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_vendor_gross_cost = models.DecimalField(max_digits=14, decimal_places=2)
    total_tds_required = models.DecimalField(max_digits=14, decimal_places=2)
    total_tds_deducted = models.DecimalField(max_digits=14, decimal_places=2)
    total_net_vendor_payable = models.DecimalField(max_digits=14, decimal_places=2)
    total_cash_paid = models.DecimalField(max_digits=14, decimal_places=2)
    remaining_cash_payable = models.DecimalField(max_digits=14, decimal_places=2)
    settlement_approval = models.ForeignKey(
        "approvals.PaymentApprovalBatch", null=True, blank=True, on_delete=models.PROTECT
    )
    settlement_status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    calculation_snapshot = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_settlements",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)


class ClientBilling(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        INVOICED = "INVOICED", "Invoiced"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Partially received"
        RECEIVED = "RECEIVED", "Received"

    trip = models.OneToOneField(Trip, on_delete=models.PROTECT, related_name="billing")
    client = models.ForeignKey("operations.Client", on_delete=models.PROTECT, related_name="billings")
    billing_amount = models.DecimalField(max_digits=14, decimal_places=2)
    invoice_no = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    payment_status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    received_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    internal_trip_costs = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_billings",
    )

    def clean(self):
        if self.client_id != self.trip.client_id:
            raise ValidationError("Billing client must match trip client")
