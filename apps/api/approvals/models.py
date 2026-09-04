
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import NumberSequence, TDSPolicy
from operations.models import Client, TimeStampedModel, Trip, Vendor


class ApprovalRule(TimeStampedModel):
    name = models.CharField(max_length=120)
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.PROTECT)
    branch = models.CharField(max_length=100, blank=True)
    purpose = models.CharField(max_length=30, default="ADVANCE")
    min_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    conditions = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["min_amount", "id"]


class ApprovalStage(TimeStampedModel):
    rule = models.ForeignKey(ApprovalRule, on_delete=models.CASCADE, related_name="stages")
    sequence = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=20, default="APPROVER")
    label = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["rule", "sequence"], name="unique_rule_stage_sequence")]
        ordering = ["sequence"]


class PaymentApprovalBatch(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
        PARTIALLY_APPROVED = "PARTIALLY_APPROVED", "Partially approved"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    approval_no = models.CharField(max_length=30, unique=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="approval_batches")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_approvals")
    submitted_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT, db_index=True)
    revision_no = models.PositiveIntegerField(default=1)
    current_stage = models.PositiveSmallIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revisions",
    )
    revision_diff = models.JSONField(default=list, blank=True)
    approval_rule_snapshot = models.JSONField(default=dict, blank=True)
    gross_requested = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    tds_requested = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net_requested = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    purpose = models.CharField(max_length=30, default="ADVANCE")

    def save(self, *args, **kwargs):
        if not self.approval_no:
            year = timezone.localdate().year
            sequence = NumberSequence.next(f"approval:{year}")
            self.approval_no = f"PA-{year}-{sequence:06d}"
        super().save(*args, **kwargs)


class PaymentApprovalItem(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    batch = models.ForeignKey(PaymentApprovalBatch, on_delete=models.PROTECT, related_name="items")
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="approval_items")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="approval_items")
    freight_rate_snapshot = models.DecimalField(max_digits=14, decimal_places=2)
    advance_percent = models.DecimalField(max_digits=5, decimal_places=2)
    freight_advance_gross = models.DecimalField(max_digits=14, decimal_places=2)
    advance_eligible_charges = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    advance_stage_deductions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gross_requested = models.DecimalField(max_digits=14, decimal_places=2)
    tds_rate = models.DecimalField(max_digits=5, decimal_places=2)
    tds_policy_snapshot = models.CharField(max_length=40, choices=TDSPolicy.choices)
    tds_base = models.DecimalField(max_digits=14, decimal_places=2)
    tds_this_request = models.DecimalField(max_digits=14, decimal_places=2)
    net_requested = models.DecimalField(max_digits=14, decimal_places=2)
    calculation_breakdown = models.JSONField(default=dict)
    item_status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT, db_index=True)
    approver_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["batch", "trip"], name="unique_trip_per_approval_batch"),
            models.CheckConstraint(condition=models.Q(gross_requested__gte=0), name="approval_gross_nonnegative"),
            models.CheckConstraint(condition=models.Q(tds_this_request__gte=0), name="approval_tds_nonnegative"),
            models.CheckConstraint(condition=models.Q(net_requested__gte=0), name="approval_net_nonnegative"),
        ]
        indexes = [models.Index(fields=["vendor", "item_status"])]


class ApprovalAction(models.Model):
    class Action(models.TextChoices):
        SUBMIT = "SUBMIT", "Submit"
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"
        SEND_BACK = "SEND_BACK", "Send back"
        CANCEL = "CANCEL", "Cancel"
        REOPEN = "REOPEN", "Reopen"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=20, choices=Action.choices)
    scope = models.CharField(max_length=10, choices=[("BATCH", "Batch"), ("ITEM", "Item")])
    batch = models.ForeignKey(PaymentApprovalBatch, on_delete=models.PROTECT, related_name="actions")
    item = models.ForeignKey(PaymentApprovalItem, null=True, blank=True, on_delete=models.PROTECT, related_name="actions")
    comment = models.TextField(blank=True)
    approval_stage = models.PositiveSmallIntegerField(default=1)
    captured_totals = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ApprovalStageDecision(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CHANGES_REQUESTED = "CHANGES_REQUESTED", "Changes requested"

    batch = models.ForeignKey(PaymentApprovalBatch, on_delete=models.PROTECT, related_name="stage_decisions")
    sequence = models.PositiveSmallIntegerField()
    role = models.CharField(max_length=20)
    label = models.CharField(max_length=100)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    decided_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["batch", "sequence"], name="unique_batch_stage_sequence")
        ]


class Comment(TimeStampedModel):
    class Visibility(models.TextChoices):
        INTERNAL = "INTERNAL", "Internal"
        TRANSPORTER_VISIBLE = "TRANSPORTER_VISIBLE", "Transporter visible"

    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=80)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="comments")
    body = models.TextField()
    visibility = models.CharField(max_length=30, choices=Visibility.choices, default=Visibility.INTERNAL)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="replies")
    mentions = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="mentioned_comments")
    attachments = models.ManyToManyField("operations.Document", blank=True, related_name="comments")
    edit_history = models.JSONField(default=list, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["object_type", "object_id", "created_at"])]
