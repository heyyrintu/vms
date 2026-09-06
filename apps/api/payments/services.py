from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.permissions import has_capability
from approvals.calculations import calculate_final_settlement, money
from approvals.models import PaymentApprovalBatch, PaymentApprovalItem
from approvals.services import submit_batch
from audit.models import record_audit
from core.models import OrganizationSettings
from operations.models import Document, Trip

from .models import (
    ClientBilling,
    FinalTripSettlement,
    FinancePaymentTransaction,
    PaymentAllocation,
    TDSEntry,
)


def paid_totals(item):
    cache = getattr(item, "_prefetched_objects_cache", {})
    if "allocations" in cache:
        rows = [row for row in cache["allocations"] if row.payment.status == FinancePaymentTransaction.Status.PAID]
        return {
            "gross": sum((row.gross_amount_allocated for row in rows), Decimal("0")),
            "tds": sum((row.tds_allocated for row in rows), Decimal("0")),
            "net": sum((row.net_cash_allocated for row in rows), Decimal("0")),
        }
    totals = item.allocations.filter(payment__status=FinancePaymentTransaction.Status.PAID).aggregate(
        gross=Sum("gross_amount_allocated"), tds=Sum("tds_allocated"), net=Sum("net_cash_allocated")
    )
    return {key: value or Decimal("0") for key, value in totals.items()}


def _update_advance_status(trip, item, paid):
    # Payment state must not rewind dispatch, delivery, cancellation or settlement.
    if trip.status not in {Trip.Status.ADVANCE_APPROVED, Trip.Status.ADVANCE_PARTIALLY_PAID, Trip.Status.ADVANCE_PAID}:
        return
    if paid["gross"] == 0:
        trip.status = Trip.Status.ADVANCE_APPROVED
    elif paid["gross"] < item.gross_requested:
        trip.status = Trip.Status.ADVANCE_PARTIALLY_PAID
    else:
        trip.status = Trip.Status.ADVANCE_PAID


@transaction.atomic
def create_paid_payment(
    *,
    actor,
    vendor,
    payment_date,
    utr_reference,
    allocations,
    bank_account=None,
    payment_mode="BANK_TRANSFER",
    remarks="",
    proof_document=None,
    request_id="",
    enforce_proof=True,
    notify=True,
):
    if not has_capability(actor, "payments.write"):
        raise PermissionError("Finance permission is required")
    if not utr_reference.strip():
        raise ValueError("UTR/reference is required")
    if enforce_proof and OrganizationSettings.load().require_payment_proof and not proof_document:
        raise ValueError("Payment proof is required by organization policy")
    if proof_document and proof_document.kind != Document.Kind.PAYMENT_PROOF:
        raise ValueError("The selected document is not payment proof")
    if bank_account and bank_account.vendor_id != vendor.pk:
        raise ValueError("The selected bank account does not belong to the payment vendor")
    normalized = []
    item_ids = [entry["approval_item_id"] for entry in allocations]
    if len(item_ids) != len(set(item_ids)):
        raise ValueError("Each approval item may be allocated only once per payment")
    items = {item.pk: item for item in PaymentApprovalItem.objects.select_for_update().select_related("trip", "vendor").filter(pk__in=item_ids)}
    if len(items) != len(set(item_ids)):
        raise ValueError("One or more approval items do not exist")
    for entry in allocations:
        item = items[entry["approval_item_id"]]
        if item.item_status != PaymentApprovalItem.Status.APPROVED:
            raise ValueError(f"Approval item {item.pk} is not approved")
        if item.vendor_id != vendor.pk:
            raise ValueError("All allocations must belong to the payment vendor")
        if item.trip.status in {Trip.Status.CANCELLED, Trip.Status.CANCELLED_WITH_PAYMENT, Trip.Status.SETTLED}:
            raise ValueError("Payments cannot be posted against cancelled or settled trips")
        gross = Decimal(str(entry["gross_amount_allocated"])).quantize(Decimal("0.01"))
        tds = Decimal(str(entry["tds_allocated"])).quantize(Decimal("0.01"))
        net = Decimal(str(entry["net_cash_allocated"])).quantize(Decimal("0.01"))
        if min(gross, tds, net) < 0 or gross != tds + net:
            raise ValueError("Each allocation must be non-negative and reconcile gross = TDS + net")
        already = paid_totals(item)
        if gross > item.gross_requested - already["gross"]:
            raise ValueError(f"Allocation exceeds remaining approved gross for item {item.pk}")
        if tds > item.tds_this_request - already["tds"]:
            raise ValueError(f"Allocation exceeds remaining approved TDS for item {item.pk}")
        if net > item.net_requested - already["net"]:
            raise ValueError(f"Allocation exceeds remaining approved net for item {item.pk}")
        normalized.append((item, gross, tds, net))
    if not normalized:
        raise ValueError("At least one allocation is required")
    gross_total = sum((row[1] for row in normalized), Decimal("0"))
    tds_total = sum((row[2] for row in normalized), Decimal("0"))
    net_total = sum((row[3] for row in normalized), Decimal("0"))
    payment = FinancePaymentTransaction(
        vendor=vendor,
        payment_date=payment_date,
        bank_account=bank_account,
        payment_mode=payment_mode,
        utr_reference=utr_reference.strip(),
        gross_allocated_amount=gross_total,
        tds_amount=tds_total,
        net_paid_amount=net_total,
        status=FinancePaymentTransaction.Status.PROCESSING,
        remarks=remarks,
        created_by=actor,
        paid_by=actor,
        paid_at=None,
        proof_document=proof_document,
    )
    payment.save()
    if proof_document:
        proof_document.object_type = "payment"
        proof_document.object_id = str(payment.pk)
        proof_document.save(update_fields=["object_type", "object_id", "updated_at"])
    for item, gross, tds, net in normalized:
        allocation = PaymentAllocation(
            payment=payment,
            approval_item=item,
            trip=item.trip,
            gross_amount_allocated=gross,
            tds_allocated=tds,
            net_cash_allocated=net,
        )
        allocation.full_clean()
        allocation.save()
        if tds:
            TDSEntry.objects.create(
                vendor=vendor,
                trip=item.trip,
                payment=payment,
                taxable_base=item.tds_base * (tds / item.tds_this_request) if item.tds_this_request else 0,
                rate=item.tds_rate,
                tds_amount=tds,
                policy_snapshot=item.tds_policy_snapshot,
                deduction_date=payment_date,
                finance_reference=payment.utr_reference,
            )
    payment.status = FinancePaymentTransaction.Status.PAID
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "paid_at", "updated_at"])
    for item, _gross, _tds, _net in normalized:
        item_paid = paid_totals(item)
        remaining = item.gross_requested - item_paid["gross"]
        if item.batch.purpose == "FINAL_SETTLEMENT":
            item.trip.status = Trip.Status.SETTLEMENT_PENDING
        else:
            _update_advance_status(item.trip, item, item_paid)
        item.trip.save(update_fields=["status", "updated_at"])
        if item.batch.purpose == "FINAL_SETTLEMENT" and remaining == 0:
            settlement = getattr(item.trip, "final_settlement", None)
            if settlement:
                paid = _paid_for_trip(item.trip)
                settlement.total_cash_paid = paid["cash"]
                settlement.total_tds_deducted = paid["tds"]
                settlement.remaining_cash_payable = max(
                    Decimal("0"), settlement.total_net_vendor_payable - paid["cash"]
                )
                settlement.settlement_status = FinalTripSettlement.Status.APPROVED
                settlement.approved_at = timezone.now()
                settlement.save(
                    update_fields=[
                        "total_cash_paid",
                        "total_tds_deducted",
                        "remaining_cash_payable",
                        "settlement_status",
                        "approved_at",
                        "updated_at",
                    ]
                )
    record_audit(actor=actor, action="PAYMENT_PAID", instance=payment, after={"utr": payment.utr_reference, "trip_ids": [row[0].trip_id for row in normalized], "net": str(net_total)}, request_id=request_id)
    if not notify:
        return payment

    from integrations.services import (
        emit_event,
        queue_message,
        render_event,
        transporter_payment_payload,
    )

    emit_event("PAYMENT_COMPLETED", instance=payment, actor=actor)
    payload = transporter_payment_payload(payment)
    body = "\n".join(
        [
            f"Payment {payload['payment_no']} processed on {payload['payment_date']}.",
            *[
                f"{line['trip_no']} | {line['route']} | Gross {line['gross']} | TDS {line['tds']} | Net {line['net']}"
                for line in payload["trips"]
            ],
            f"UTR: {payload['utr_reference']}",
        ]
    )
    if vendor.email:
        subject, rendered_body = render_event(
            "PAYMENT_COMPLETED",
            {
                "reference": payment.payment_no,
                "vendor": vendor.display_name,
                "trip_lines": body,
                "gross": payment.gross_allocated_amount,
                "tds": payment.tds_amount,
                "net": payment.net_paid_amount,
                "utr": payment.utr_reference,
            },
            channel="EMAIL",
            fallback_subject=f"[{payment.payment_no}] Drona Logitech payment confirmation",
            fallback_body=body,
        )
        queue_message(
            channel="EMAIL",
            recipient=vendor.email,
            subject=subject,
            body=rendered_body,
            object_type="payment",
            object_id=payment.pk,
            idempotency_key=f"payment-email:{payment.pk}",
            vendor=vendor,
            event_key="PAYMENT_COMPLETED",
            actor=actor,
        )
    if vendor.primary_phone:
        subject, rendered_body = render_event(
            "PAYMENT_COMPLETED",
            {
                "reference": payment.payment_no,
                "vendor": vendor.display_name,
                "trip_lines": body,
                "gross": payment.gross_allocated_amount,
                "tds": payment.tds_amount,
                "net": payment.net_paid_amount,
                "utr": payment.utr_reference,
            },
            channel="WHATSAPP",
            fallback_subject="Payment completed",
            fallback_body=body,
        )
        queue_message(
            channel="WHATSAPP",
            recipient=vendor.primary_phone,
            subject=subject,
            body=rendered_body,
            object_type="payment",
            object_id=payment.pk,
            idempotency_key=f"payment-whatsapp:{payment.pk}",
            vendor=vendor,
            event_key="PAYMENT_COMPLETED",
            actor=actor,
        )
    return payment


@transaction.atomic
def reverse_payment(*, actor, payment, reason, request_id=""):
    if not has_capability(actor, "payments.write"):
        raise PermissionError("Finance permission is required")
    if not reason.strip():
        raise ValueError("Reversal reason is required")
    payment = FinancePaymentTransaction.objects.select_for_update().get(pk=payment.pk)
    if payment.status != payment.Status.PAID:
        raise ValueError("Only paid transactions can be reversed")
    allocations = list(payment.allocations.select_related("approval_item", "trip").order_by("trip_id", "id"))
    locked_trips = {trip.pk: trip for trip in Trip.objects.select_for_update().filter(
        pk__in=[allocation.trip_id for allocation in allocations]
    ).order_by("pk")}
    if any(trip.status == Trip.Status.SETTLED for trip in locked_trips.values()):
        raise ValueError("Payments on settled trips cannot be reversed. Reopen the settlement first.")
    payment.status = payment.Status.REVERSED
    payment.reversal_reason = reason
    payment.save(update_fields=["status", "reversal_reason", "updated_at"])
    payment.tds_entries.update(status="REVERSED")
    for allocation in allocations:
        allocation.trip = locked_trips[allocation.trip_id]
        item = allocation.approval_item
        paid = paid_totals(item)
        if item.batch.purpose == "FINAL_SETTLEMENT":
            allocation.trip.status = Trip.Status.SETTLEMENT_PENDING
            settlement = getattr(allocation.trip, "final_settlement", None)
            if settlement:
                trip_paid = _paid_for_trip(allocation.trip)
                settlement.total_cash_paid = trip_paid["cash"]
                settlement.total_tds_deducted = trip_paid["tds"]
                settlement.remaining_cash_payable = max(
                    Decimal("0"), settlement.total_net_vendor_payable - trip_paid["cash"]
                )
                settlement.settlement_status = FinalTripSettlement.Status.APPROVED
                settlement.save(
                    update_fields=[
                        "total_cash_paid",
                        "total_tds_deducted",
                        "remaining_cash_payable",
                        "settlement_status",
                        "updated_at",
                    ]
                )
        else:
            _update_advance_status(allocation.trip, item, paid)
        allocation.trip.save(update_fields=["status", "updated_at"])
    record_audit(actor=actor, action="PAYMENT_REVERSED", instance=payment, before={"status": "PAID"}, after={"status": "REVERSED", "reason": reason}, request_id=request_id)
    return payment


def _paid_for_trip(trip):
    allocations = trip.payment_allocations.filter(payment__status=FinancePaymentTransaction.Status.PAID)
    return {
        "cash": allocations.aggregate(total=Sum("net_cash_allocated"))["total"] or Decimal("0"),
        "tds": allocations.aggregate(total=Sum("tds_allocated"))["total"] or Decimal("0"),
    }


def settlement_documents_ready(trip):
    policy = OrganizationSettings.load()
    kinds = set(
        Document.objects.filter(object_type="trip", object_id=str(trip.pk), scan_status="CLEAN").values_list(
            "kind", flat=True
        )
    )
    missing = []
    if policy.require_pod_for_settlement and Document.Kind.POD not in kinds:
        missing.append("POD")
    if policy.require_vendor_invoice_for_settlement and Document.Kind.VENDOR_INVOICE not in kinds:
        missing.append("VENDOR_INVOICE")
    return missing


@transaction.atomic
def save_settlement(
    *, actor, trip, final_freight, additive_charges=0, vendor_deductions=0, request_id=""
):
    if not has_capability(actor, "trips.write"):
        raise PermissionError("Operations permission is required")
    trip = Trip.objects.select_for_update().select_related("vendor").get(pk=trip.pk)
    if trip.status not in {Trip.Status.DELIVERED, Trip.Status.SETTLEMENT_PENDING, Trip.Status.SETTLEMENT_APPROVAL_PENDING}:
        raise ValueError("Trip must be delivered before final settlement")
    existing = FinalTripSettlement.objects.select_for_update().filter(trip=trip).first()
    if existing and existing.settlement_status != FinalTripSettlement.Status.DRAFT:
        raise ValueError(
            "Submitted or approved settlement values are immutable; send the settlement back before revising it"
        )
    paid = _paid_for_trip(trip)
    settings = OrganizationSettings.load()
    rate = trip.vendor.default_tds_rate if trip.vendor.default_tds_rate is not None else settings.default_tds_rate
    gross = money(Decimal(str(final_freight)) + Decimal(str(additive_charges)) - Decimal(str(vendor_deductions)))
    total_tds_required = money(gross * rate / Decimal("100"))
    result = calculate_final_settlement(
        final_freight=final_freight,
        additive_charges=additive_charges,
        vendor_deductions=vendor_deductions,
        total_tds_required=total_tds_required,
        total_cash_paid=paid["cash"],
    )
    calculation_snapshot = {
        "final_freight": str(money(final_freight)),
        "additive_charges": str(money(additive_charges)),
        "vendor_deductions": str(money(vendor_deductions)),
        **{key: str(value) for key, value in result.items()},
    }
    settlement, _ = FinalTripSettlement.objects.update_or_create(
        trip=trip,
        defaults={
            "final_freight": money(final_freight),
            "additive_charges": money(additive_charges),
            "vendor_deductions": money(vendor_deductions),
            "total_vendor_gross_cost": result["final_vendor_gross_cost"],
            "total_tds_required": result["total_tds_required"],
            "total_tds_deducted": paid["tds"],
            "total_net_vendor_payable": result["net_vendor_payable_total"],
            "total_cash_paid": result["total_cash_paid"],
            "remaining_cash_payable": max(Decimal("0"), result["remaining_cash_payable"]),
            "calculation_snapshot": calculation_snapshot,
            "created_by": existing.created_by if existing else actor,
        },
    )
    trip.status = Trip.Status.SETTLEMENT_PENDING
    trip.settlement_status = "PENDING"
    trip.save(update_fields=["status", "settlement_status", "updated_at"])
    record_audit(actor=actor, action="SETTLEMENT_CALCULATED", instance=settlement, after=settlement.calculation_snapshot, request_id=request_id)
    return settlement


def _settlement_revision_context(settlement):
    previous = (
        PaymentApprovalBatch.objects.filter(
            items__trip=settlement.trip,
            purpose="FINAL_SETTLEMENT",
        )
        .exclude(status=PaymentApprovalBatch.Status.DRAFT)
        .order_by("-revision_no", "-created_at")
        .first()
    )
    if not previous:
        return None, 1, []
    old_snapshot = (
        previous.items.filter(trip=settlement.trip)
        .values_list("calculation_breakdown", flat=True)
        .first()
        or {}
    )
    fields = (
        "final_freight",
        "additive_charges",
        "vendor_deductions",
        "final_vendor_gross_cost",
        "total_tds_required",
        "net_vendor_payable_total",
        "total_cash_paid",
        "remaining_cash_payable",
    )
    diff = [
        {
            "trip_id": settlement.trip_id,
            "field": field,
            "old": str(old_snapshot.get(field)),
            "new": str(settlement.calculation_snapshot.get(field)),
        }
        for field in fields
        if str(old_snapshot.get(field)) != str(settlement.calculation_snapshot.get(field))
    ]
    return previous, previous.revision_no + 1, diff


@transaction.atomic
def submit_settlement(*, actor, settlement, request_id=""):
    settlement = FinalTripSettlement.objects.select_for_update().select_related("trip__client", "trip__vendor").get(pk=settlement.pk)
    if settlement.settlement_status != FinalTripSettlement.Status.DRAFT:
        raise ValueError("Only a draft settlement can be submitted")
    missing = settlement_documents_ready(settlement.trip)
    if missing:
        raise ValueError(f"Required settlement documents are missing: {', '.join(missing)}")
    remaining_tds = max(Decimal("0"), settlement.total_tds_required - settlement.total_tds_deducted)
    if settlement.remaining_cash_payable <= 0 and remaining_tds <= 0:
        settlement.settlement_status = FinalTripSettlement.Status.APPROVED
        settlement.approved_at = timezone.now()
        settlement.save(update_fields=["settlement_status", "approved_at", "updated_at"])
        return settlement
    previous, revision_no, revision_diff = _settlement_revision_context(settlement)
    if previous and previous.items.filter(
        trip=settlement.trip,
        allocations__payment__status=FinancePaymentTransaction.Status.PAID,
    ).exists():
        raise ValueError("A paid settlement approval cannot be superseded")
    batch = PaymentApprovalBatch.objects.create(
        client=settlement.trip.client,
        requested_by=actor,
        purpose="FINAL_SETTLEMENT",
        supersedes=previous,
        revision_no=revision_no,
        revision_diff=revision_diff,
    )
    gross = money(settlement.remaining_cash_payable + remaining_tds)
    item = PaymentApprovalItem.objects.create(
        batch=batch,
        trip=settlement.trip,
        vendor=settlement.trip.vendor,
        freight_rate_snapshot=settlement.final_freight,
        advance_percent=Decimal("100"),
        freight_advance_gross=gross,
        advance_eligible_charges=Decimal("0"),
        advance_stage_deductions=Decimal("0"),
        gross_requested=gross,
        tds_rate=(remaining_tds / gross * Decimal("100")) if gross else Decimal("0"),
        tds_policy_snapshot="CUMULATIVE_TRIP_LIABILITY",
        tds_base=settlement.total_vendor_gross_cost,
        tds_this_request=remaining_tds,
        net_requested=settlement.remaining_cash_payable,
        calculation_breakdown={"settlement_id": settlement.pk, **settlement.calculation_snapshot},
    )
    batch.gross_requested = item.gross_requested
    batch.tds_requested = item.tds_this_request
    batch.net_requested = item.net_requested
    batch.save(update_fields=["gross_requested", "tds_requested", "net_requested", "updated_at"])
    if previous:
        previous.items.filter(trip=settlement.trip).update(
            item_status=PaymentApprovalItem.Status.SUPERSEDED
        )
        if not previous.items.exclude(
            item_status=PaymentApprovalItem.Status.SUPERSEDED
        ).exists():
            previous.status = PaymentApprovalBatch.Status.SUPERSEDED
            previous.save(update_fields=["status", "updated_at"])
    submit_batch(batch=batch, actor=actor, request_id=request_id)
    settlement.settlement_approval = batch
    settlement.settlement_status = FinalTripSettlement.Status.APPROVAL_PENDING
    settlement.save(update_fields=["settlement_approval", "settlement_status", "updated_at"])
    settlement.trip.status = Trip.Status.SETTLEMENT_APPROVAL_PENDING
    settlement.trip.settlement_status = "APPROVAL_PENDING"
    settlement.trip.save(update_fields=["status", "settlement_status", "updated_at"])
    return settlement


@transaction.atomic
def finalize_settlement(*, actor, settlement, request_id=""):
    settlement = FinalTripSettlement.objects.select_for_update().select_related("trip").get(pk=settlement.pk)
    paid = _paid_for_trip(settlement.trip)
    settlement.total_cash_paid = paid["cash"]
    settlement.total_tds_deducted = paid["tds"]
    settlement.remaining_cash_payable = max(Decimal("0"), settlement.total_net_vendor_payable - paid["cash"])
    if settlement.remaining_cash_payable > 0 or settlement.total_tds_deducted < settlement.total_tds_required:
        raise ValueError("Settlement still has unpaid cash or TDS")
    missing = settlement_documents_ready(settlement.trip)
    if missing:
        raise ValueError(f"Required settlement documents are missing: {', '.join(missing)}")
    billing = getattr(settlement.trip, "billing", None)
    if not billing or billing.payment_status == ClientBilling.Status.DRAFT:
        raise ValueError("Client billing must be invoiced before the trip can be settled")
    settlement.settlement_status = FinalTripSettlement.Status.SETTLED
    settlement.settled_at = timezone.now()
    settlement.save(
        update_fields=[
            "total_cash_paid",
            "total_tds_deducted",
            "remaining_cash_payable",
            "settlement_status",
            "settled_at",
            "updated_at",
        ]
    )
    settlement.trip.status = Trip.Status.SETTLED
    settlement.trip.settlement_status = "SETTLED"
    settlement.trip.save(update_fields=["status", "settlement_status", "updated_at"])
    record_audit(actor=actor, action="TRIP_SETTLED", instance=settlement.trip, after={"settlement_id": settlement.pk}, request_id=request_id)
    return settlement
