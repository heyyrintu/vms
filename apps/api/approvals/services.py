from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.permissions import has_capability
from audit.models import record_audit
from core.models import OrganizationSettings
from operations.models import Trip, TripCharge

from .calculations import calculate_advance
from .models import (
    ApprovalAction,
    ApprovalRule,
    ApprovalStageDecision,
    PaymentApprovalBatch,
    PaymentApprovalItem,
)


def _resolved_policy(trip):
    settings = OrganizationSettings.load()
    return (
        trip.vendor.default_tds_policy or settings.default_tds_policy,
        trip.vendor.default_tds_rate if trip.vendor.default_tds_rate is not None else settings.default_tds_rate,
    )


def calculate_trip_advance(trip, *, manual_tds=None, manual_tds_base=None, manual_reason=""):
    settings = OrganizationSettings.load()
    policy, rate = _resolved_policy(trip)
    charges = trip.charges.filter(advance_eligible=True)
    additions = charges.filter(direction=TripCharge.Direction.ADD).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    deductions = charges.filter(direction=TripCharge.Direction.DEDUCT).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    taxable_additions = charges.filter(direction=TripCharge.Direction.ADD, tds_eligible=True).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    taxable_deductions = charges.filter(direction=TripCharge.Direction.DEDUCT, tds_eligible=True).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    advance_percent = trip.advance_percent if trip.advance_percent is not None else settings.default_advance_percent
    freight_advance = trip.vendor_freight_rate * advance_percent / Decimal("100")
    current_taxable = freight_advance + taxable_additions - taxable_deductions
    previous_tds = (
        trip.tds_entries.filter(status="POSTED").aggregate(total=Sum("tds_amount"))["total"] or Decimal("0")
    )
    return calculate_advance(
        freight_rate=trip.vendor_freight_rate,
        advance_percent=advance_percent,
        advance_eligible_charges=additions,
        advance_stage_deductions=deductions,
        tds_rate=rate,
        tds_policy=policy,
        current_taxable_amount=current_taxable,
        cumulative_taxable_base=trip.vendor_freight_rate + taxable_additions - taxable_deductions,
        previous_tds=previous_tds,
        manual_tds=manual_tds,
        manual_tds_base=manual_tds_base,
        manual_reason=manual_reason,
    )


def _recalculate_batch(batch):
    totals = batch.items.exclude(item_status=PaymentApprovalItem.Status.SUPERSEDED).aggregate(
        gross=Sum("gross_requested"), tds=Sum("tds_this_request"), net=Sum("net_requested")
    )
    batch.gross_requested = totals["gross"] or 0
    batch.tds_requested = totals["tds"] or 0
    batch.net_requested = totals["net"] or 0
    batch.save(update_fields=["gross_requested", "tds_requested", "net_requested", "updated_at"])


def _revision_context(trips, purpose):
    previous = (
        PaymentApprovalBatch.objects.filter(items__trip__in=trips, purpose=purpose)
        .exclude(status=PaymentApprovalBatch.Status.DRAFT)
        .order_by("-created_at")
        .distinct()
        .first()
    )
    if not previous:
        return None, 1, []
    old_by_trip = {item.trip_id: item for item in previous.items.all()}
    diff = []
    for trip in trips:
        old = old_by_trip.get(trip.pk)
        if not old:
            diff.append({"trip_id": trip.pk, "field": "trip", "old": None, "new": trip.trip_no})
            continue
        for field, current in (
            ("vendor", trip.vendor_id),
            ("vendor_freight_rate", trip.vendor_freight_rate),
            ("advance_percent", trip.advance_percent),
        ):
            prior = old.vendor_id if field == "vendor" else getattr(old, f"{field}_snapshot", getattr(old, field, None))
            if str(prior) != str(current):
                diff.append({"trip_id": trip.pk, "field": field, "old": str(prior), "new": str(current)})
    return previous, previous.revision_no + 1, diff


def refresh_batch_status_from_items(batch):
    statuses = set(
        batch.items.exclude(item_status=PaymentApprovalItem.Status.SUPERSEDED).values_list(
            "item_status", flat=True
        )
    )
    if not statuses:
        status = PaymentApprovalBatch.Status.SUPERSEDED
    elif statuses == {PaymentApprovalItem.Status.APPROVED}:
        status = PaymentApprovalBatch.Status.APPROVED
    elif PaymentApprovalItem.Status.APPROVED in statuses:
        status = PaymentApprovalBatch.Status.PARTIALLY_APPROVED
    elif PaymentApprovalItem.Status.CHANGES_REQUESTED in statuses:
        status = PaymentApprovalBatch.Status.CHANGES_REQUESTED
    elif statuses == {PaymentApprovalItem.Status.REJECTED}:
        status = PaymentApprovalBatch.Status.REJECTED
    else:
        status = batch.status
    if batch.status != status:
        batch.status = status
        batch.save(update_fields=["status", "updated_at"])
    return status


@transaction.atomic
def create_approval_batch(*, actor, trips, purpose="ADVANCE", request_id=""):
    trip_ids = [t.pk if hasattr(t, "pk") else t for t in trips]
    if len(trip_ids) != len(set(trip_ids)):
        raise ValueError("Each trip may be selected only once")
    trips = list(Trip.objects.select_for_update().select_related("client", "vendor").filter(pk__in=trip_ids))
    if len(trips) != len(trip_ids):
        raise ValueError("One or more selected trips no longer exist. Refresh the trip list.")
    if not trips:
        raise ValueError("At least one trip is required")
    if len({trip.client_id for trip in trips}) != 1:
        raise ValueError("An approval batch must belong to one client")
    for trip in trips:
        if trip.vendor.status != trip.vendor.Status.ACTIVE:
            raise ValueError(f"Vendor {trip.vendor.display_name} is not active")
        if trip.status not in {Trip.Status.READY, Trip.Status.DRAFT}:
            raise ValueError(f"Trip {trip.trip_no} is not eligible for approval")
        active = trip.approval_items.exclude(item_status__in=[
            PaymentApprovalItem.Status.REJECTED,
            PaymentApprovalItem.Status.CHANGES_REQUESTED,
            PaymentApprovalItem.Status.SUPERSEDED,
        ]).select_related("batch").first()
        if active:
            raise ValueError(
                f"Trip {trip.trip_no} already belongs to approval {active.batch.approval_no}. "
                "Open the existing approval from the approval inbox; submit it if it is a draft."
            )
    previous, revision_no, revision_diff = _revision_context(trips, purpose)
    batch = PaymentApprovalBatch.objects.create(
        client=trips[0].client,
        requested_by=actor,
        purpose=purpose,
        supersedes=previous,
        revision_no=revision_no,
        revision_diff=revision_diff,
    )
    for trip in trips:
        calculation = calculate_trip_advance(trip)
        PaymentApprovalItem.objects.create(
            batch=batch,
            trip=trip,
            vendor=trip.vendor,
            freight_rate_snapshot=calculation.freight_rate,
            advance_percent=calculation.advance_percent,
            freight_advance_gross=calculation.freight_advance_gross,
            advance_eligible_charges=calculation.advance_eligible_charges,
            advance_stage_deductions=calculation.advance_stage_deductions,
            gross_requested=calculation.gross_requested,
            tds_rate=calculation.tds_rate,
            tds_policy_snapshot=calculation.tds_policy,
            tds_base=calculation.tds_base,
            tds_this_request=calculation.tds_this_payment,
            net_requested=calculation.net_requested,
            calculation_breakdown=calculation.as_dict(),
        )
    _recalculate_batch(batch)
    if previous:
        previous.items.filter(trip__in=trips).update(
            item_status=PaymentApprovalItem.Status.SUPERSEDED
        )
        refresh_batch_status_from_items(previous)
    record_audit(actor=actor, action="APPROVAL_BATCH_CREATED", instance=batch, after={"trip_ids": [t.pk for t in trips]}, request_id=request_id)
    return batch


def _rule_snapshot(batch):
    branch = batch.items.select_related("trip").values_list("trip__branch", flat=True).first() or ""
    candidates = ApprovalRule.objects.filter(active=True, purpose=batch.purpose, min_amount__lte=batch.gross_requested).prefetch_related("stages")
    matches = []
    for rule in candidates:
        if rule.client_id and rule.client_id != batch.client_id:
            continue
        if rule.branch and rule.branch != branch:
            continue
        if rule.max_amount is not None and batch.gross_requested > rule.max_amount:
            continue
        individual_limit = rule.conditions.get("max_individual_trip_amount")
        if individual_limit and any(item.gross_requested > Decimal(str(individual_limit)) for item in batch.items.all()):
            continue
        matches.append(rule)
    rule = sorted(matches, key=lambda item: (bool(item.client_id), bool(item.branch), item.min_amount), reverse=True)[0] if matches else None
    stages = list(rule.stages.order_by("sequence")) if rule else []
    if not stages:
        return {"rule_id": None, "rule_name": "Default approval", "stages": [{"sequence": 1, "role": "APPROVER", "label": "Manager approval"}]}
    return {
        "rule_id": rule.pk,
        "rule_name": rule.name,
        "conditions": rule.conditions,
        "stages": [{"sequence": stage.sequence, "role": stage.role, "label": stage.label} for stage in stages],
    }


@transaction.atomic
def submit_batch(*, batch, actor, request_id=""):
    batch = PaymentApprovalBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.requested_by_id != actor.id and not has_capability(actor, "*"):
        raise PermissionError("Only the requester or an administrator can submit this batch")
    if batch.status == batch.Status.CHANGES_REQUESTED:
        raise ValueError("Returned approvals require a new revision. Review the trip values and create a new approval from the builder.")
    if batch.status != batch.Status.DRAFT:
        raise ValueError("Only draft batches can be submitted")
    trips = list(Trip.objects.select_for_update().filter(pk__in=batch.items.values("trip_id")).order_by("pk"))
    if any(trip.status in {Trip.Status.CANCELLED, Trip.Status.CANCELLED_WITH_PAYMENT, Trip.Status.SETTLED} for trip in trips):
        raise ValueError("Cancelled or settled trips cannot be submitted for approval")
    batch.status = batch.Status.PENDING
    batch.submitted_at = timezone.now()
    batch.approval_rule_snapshot = _rule_snapshot(batch)
    batch.current_stage = batch.approval_rule_snapshot["stages"][0]["sequence"]
    batch.save(update_fields=["status", "submitted_at", "approval_rule_snapshot", "current_stage", "updated_at"])
    batch.stage_decisions.all().delete()
    ApprovalStageDecision.objects.bulk_create(
        [
            ApprovalStageDecision(
                batch=batch,
                sequence=stage["sequence"],
                role=stage["role"],
                label=stage.get("label", stage["role"]),
            )
            for stage in batch.approval_rule_snapshot["stages"]
        ]
    )
    batch.items.filter(item_status__in=[PaymentApprovalItem.Status.DRAFT, PaymentApprovalItem.Status.CHANGES_REQUESTED]).update(item_status=PaymentApprovalItem.Status.PENDING)
    for item in batch.items.all():
        if item.trip.status in {Trip.Status.DRAFT, Trip.Status.READY}:
            item.trip.status = Trip.Status.ADVANCE_APPROVAL_PENDING
            item.trip.save(update_fields=["status", "updated_at"])
    ApprovalAction.objects.create(
        actor=actor,
        action=ApprovalAction.Action.SUBMIT,
        scope="BATCH",
        batch=batch,
        captured_totals={"gross": str(batch.gross_requested), "tds": str(batch.tds_requested), "net": str(batch.net_requested)},
    )
    record_audit(actor=actor, action="APPROVAL_SUBMITTED", instance=batch, after={"status": batch.status}, request_id=request_id)
    from integrations.services import emit_event

    emit_event("APPROVAL_REQUESTED", instance=batch, actor=actor)
    return batch


@transaction.atomic
def decide_batch(*, batch, actor, decision, item_ids=None, comment="", request_id=""):
    settings = OrganizationSettings.load()
    batch = PaymentApprovalBatch.objects.select_for_update().get(pk=batch.pk)
    stage = batch.stage_decisions.select_for_update().filter(sequence=batch.current_stage).first()
    if not has_capability(actor, "approvals.decide") and not (
        stage and actor.role == stage.role
    ):
        raise PermissionError("The current approval stage is not assigned to this user role")
    if actor.id == batch.requested_by_id and not settings.allow_self_approval:
        raise PermissionError("Self-approval is disabled")
    if batch.status not in {batch.Status.PENDING, batch.Status.PARTIALLY_APPROVED}:
        raise ValueError("Batch is not awaiting a decision")
    if decision in {ApprovalAction.Action.REJECT, ApprovalAction.Action.SEND_BACK} and not comment.strip():
        raise ValueError("A reason is required for reject or send back")
    if stage and actor.role != stage.role and not has_capability(actor, "*"):
        raise PermissionError(f"The current stage requires the {stage.role} role")
    pending_items = batch.items.filter(item_status=PaymentApprovalItem.Status.PENDING)
    if item_ids:
        pending_items = pending_items.filter(pk__in=item_ids)
    locked_trips = list(Trip.objects.select_for_update().filter(pk__in=pending_items.values("trip_id")).order_by("pk"))
    if any(trip.status in {Trip.Status.CANCELLED, Trip.Status.CANCELLED_WITH_PAYMENT, Trip.Status.SETTLED} for trip in locked_trips):
        raise ValueError("Cancelled or settled trips cannot receive approval decisions. Select only open trip lines.")
    pending_stages = list(batch.stage_decisions.filter(status=ApprovalStageDecision.Status.PENDING))
    final_stage = not stage or (pending_stages and stage.pk == pending_stages[-1].pk)
    if decision == ApprovalAction.Action.APPROVE and not final_stage:
        if item_ids:
            raise ValueError("Line-level approval is available at the final approval stage")
        stage.status = ApprovalStageDecision.Status.APPROVED
        stage.decided_by = actor
        stage.decided_at = timezone.now()
        stage.comment = comment
        stage.save(update_fields=["status", "decided_by", "decided_at", "comment", "updated_at"])
        next_stage = batch.stage_decisions.filter(sequence__gt=stage.sequence).order_by("sequence").first()
        batch.current_stage = next_stage.sequence
        batch.save(update_fields=["current_stage", "updated_at"])
        ApprovalAction.objects.create(
            actor=actor,
            action=decision,
            scope="BATCH",
            batch=batch,
            comment=comment,
            approval_stage=stage.sequence,
            captured_totals={"gross": str(batch.gross_requested), "tds": str(batch.tds_requested), "net": str(batch.net_requested)},
        )
        record_audit(actor=actor, action="APPROVAL_STAGE_APPROVED", instance=batch, after={"stage": stage.sequence, "next_stage": next_stage.sequence}, request_id=request_id)
        from integrations.services import emit_event

        emit_event("APPROVAL_REQUESTED", instance=batch, actor=actor)
        return batch

    target = batch.items.select_for_update().filter(item_status=PaymentApprovalItem.Status.PENDING)
    if item_ids:
        target = target.filter(pk__in=item_ids)
    target = list(target)
    if not target:
        raise ValueError("No pending approval items selected")
    status_map = {
        ApprovalAction.Action.APPROVE: PaymentApprovalItem.Status.APPROVED,
        ApprovalAction.Action.REJECT: PaymentApprovalItem.Status.REJECTED,
        ApprovalAction.Action.SEND_BACK: PaymentApprovalItem.Status.CHANGES_REQUESTED,
    }
    if decision not in status_map:
        raise ValueError("Unsupported approval decision")
    for item in target:
        item.item_status = status_map[decision]
        item.approver_note = comment
        item.save(update_fields=["item_status", "approver_note", "updated_at"])
        if decision == ApprovalAction.Action.APPROVE:
            item.trip.status = (
                Trip.Status.SETTLEMENT_APPROVAL_PENDING
                if batch.purpose == "FINAL_SETTLEMENT"
                else Trip.Status.ADVANCE_APPROVED
            )
            if batch.purpose == "FINAL_SETTLEMENT" and hasattr(item.trip, "final_settlement"):
                item.trip.final_settlement.settlement_status = "APPROVED"
                item.trip.final_settlement.approved_at = timezone.now()
                item.trip.final_settlement.save(
                    update_fields=["settlement_status", "approved_at", "updated_at"]
                )
        elif decision in {ApprovalAction.Action.REJECT, ApprovalAction.Action.SEND_BACK}:
            item.trip.status = (
                Trip.Status.SETTLEMENT_PENDING
                if batch.purpose == "FINAL_SETTLEMENT"
                else Trip.Status.READY
            )
            if batch.purpose == "FINAL_SETTLEMENT" and hasattr(item.trip, "final_settlement"):
                item.trip.final_settlement.settlement_status = "DRAFT"
                item.trip.final_settlement.approved_at = None
                item.trip.final_settlement.save(
                    update_fields=["settlement_status", "approved_at", "updated_at"]
                )
        item.trip.save(update_fields=["status", "updated_at"])
        ApprovalAction.objects.create(
            actor=actor,
            action=decision,
            scope="ITEM",
            batch=batch,
            item=item,
            comment=comment,
            captured_totals={"gross": str(item.gross_requested), "tds": str(item.tds_this_request), "net": str(item.net_requested)},
        )
    refresh_batch_status_from_items(batch)
    if stage and batch.status in {batch.Status.APPROVED, batch.Status.REJECTED, batch.Status.CHANGES_REQUESTED}:
        stage.status = {
            batch.Status.APPROVED: ApprovalStageDecision.Status.APPROVED,
            batch.Status.REJECTED: ApprovalStageDecision.Status.REJECTED,
            batch.Status.CHANGES_REQUESTED: ApprovalStageDecision.Status.CHANGES_REQUESTED,
        }[batch.status]
        stage.decided_by = actor
        stage.decided_at = timezone.now()
        stage.comment = comment
        stage.save(update_fields=["status", "decided_by", "decided_at", "comment", "updated_at"])
    record_audit(actor=actor, action=f"APPROVAL_{decision}", instance=batch, after={"item_ids": [i.pk for i in target], "status": batch.status}, request_id=request_id)
    from integrations.services import emit_event

    event = {"APPROVE": "APPROVAL_COMPLETED", "REJECT": "APPROVAL_REJECTED", "SEND_BACK": "CHANGES_REQUESTED"}[decision]
    emit_event(event, instance=batch, actor=actor)
    if decision == ApprovalAction.Action.APPROVE:
        from integrations.services import queue_message, render_event

        emit_event("FINANCE_READY", instance=batch, actor=actor)
        vendor_ids = {item.vendor_id for item in target}
        for vendor_id in vendor_ids:
            vendor_items = [item for item in target if item.vendor_id == vendor_id]
            vendor = vendor_items[0].vendor
            item_key = "-".join(str(item.pk) for item in sorted(vendor_items, key=lambda row: row.pk))
            body = "\n".join(
                [
                    f"Approval {batch.approval_no} accepted for processing.",
                    *[
                        f"{item.trip.trip_no} | {item.trip.origin} → {item.trip.destination} | Gross {item.gross_requested} | TDS {item.tds_this_request} | Net {item.net_requested}"
                        for item in vendor_items
                    ],
                ]
            )
            if vendor.email:
                subject, rendered_body = render_event(
                    "APPROVAL_COMPLETED",
                    {
                        "reference": batch.approval_no,
                        "vendor": vendor.display_name,
                        "trip_lines": body,
                        "gross": sum(item.gross_requested for item in vendor_items),
                        "tds": sum(item.tds_this_request for item in vendor_items),
                        "net": sum(item.net_requested for item in vendor_items),
                    },
                    channel="EMAIL",
                    fallback_subject=f"[{batch.approval_no}] Drona Logitech payment approval",
                    fallback_body=body,
                )
                queue_message(
                    channel="EMAIL",
                    recipient=vendor.email,
                    subject=subject,
                    body=rendered_body,
                    object_type="approval",
                    object_id=batch.pk,
                    idempotency_key=(
                        f"approval-email:{batch.pk}:{vendor.pk}:{batch.revision_no}:{item_key}"
                    ),
                    vendor=vendor,
                    event_key="APPROVAL_COMPLETED",
                    actor=actor,
                )
            if vendor.primary_phone:
                subject, rendered_body = render_event(
                    "APPROVAL_COMPLETED",
                    {
                        "reference": batch.approval_no,
                        "vendor": vendor.display_name,
                        "trip_lines": body,
                        "gross": sum(item.gross_requested for item in vendor_items),
                        "tds": sum(item.tds_this_request for item in vendor_items),
                        "net": sum(item.net_requested for item in vendor_items),
                    },
                    channel="WHATSAPP",
                    fallback_subject="Payment approval",
                    fallback_body=body,
                )
                queue_message(
                    channel="WHATSAPP",
                    recipient=vendor.primary_phone,
                    subject=subject,
                    body=rendered_body,
                    object_type="approval",
                    object_id=batch.pk,
                    idempotency_key=(
                        f"approval-whatsapp:{batch.pk}:{vendor.pk}:{batch.revision_no}:{item_key}"
                    ),
                    vendor=vendor,
                    event_key="APPROVAL_COMPLETED",
                    actor=actor,
                )
    return batch
