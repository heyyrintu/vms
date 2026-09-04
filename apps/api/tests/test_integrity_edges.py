from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from approvals.models import ApprovalAction, PaymentApprovalItem
from approvals.services import create_approval_batch, decide_batch, submit_batch
from integrations.models import IntegrationMessage, NotificationTemplate
from integrations.services import persist_whatsapp_media, render_event
from operations.models import Document, Trip, TripRecovery
from payments.models import FinancePaymentTransaction
from payments.services import (
    create_paid_payment,
    reverse_payment,
    save_settlement,
    submit_settlement,
)


def _clean_document(trip, actor, kind, name):
    return Document.objects.create(
        object_type="trip",
        object_id=str(trip.pk),
        kind=kind,
        file=ContentFile(b"%PDF-1.4\n", name=name),
        original_name=name,
        content_type="application/pdf",
        size=9,
        sha256=("a" if kind == Document.Kind.POD else "b") * 64,
        scan_status="CLEAN",
        uploaded_by=actor,
    )


def _approved_advance_payment(trip, users, reference):
    operations = users[User.Role.OPERATIONS]
    batch = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=batch, actor=operations)
    decide_batch(
        batch=batch,
        actor=users[User.Role.APPROVER],
        decision=ApprovalAction.Action.APPROVE,
    )
    item = batch.items.get()
    payment = create_paid_payment(
        actor=users[User.Role.FINANCE],
        vendor=trip.vendor,
        payment_date=timezone.localdate(),
        utr_reference=reference,
        allocations=[
            {
                "approval_item_id": item.pk,
                "gross_amount_allocated": item.gross_requested,
                "tds_allocated": item.tds_this_request,
                "net_cash_allocated": item.net_requested,
            }
        ],
    )
    return payment


@pytest.mark.django_db
def test_returned_settlement_is_revised_without_overwriting_history(trip_factory, users):
    trip = trip_factory(1)
    operations = users[User.Role.OPERATIONS]
    trip.status = Trip.Status.DELIVERED
    trip.actual_delivery_at = timezone.now()
    trip.save(update_fields=["status", "actual_delivery_at", "updated_at"])
    _clean_document(trip, operations, Document.Kind.POD, "pod.pdf")
    _clean_document(trip, operations, Document.Kind.VENDOR_INVOICE, "invoice.pdf")

    settlement = save_settlement(actor=operations, trip=trip, final_freight="52000")
    submit_settlement(actor=operations, settlement=settlement)
    settlement.refresh_from_db()
    first_batch = settlement.settlement_approval

    with pytest.raises(ValueError, match="immutable"):
        save_settlement(actor=operations, trip=trip, final_freight="53000")

    decide_batch(
        batch=first_batch,
        actor=users[User.Role.APPROVER],
        decision=ApprovalAction.Action.SEND_BACK,
        comment="Correct the final freight.",
    )
    settlement.refresh_from_db()
    assert settlement.settlement_status == settlement.Status.DRAFT

    settlement = save_settlement(actor=operations, trip=trip, final_freight="53000")
    submit_settlement(actor=operations, settlement=settlement)
    settlement.refresh_from_db()
    first_batch.refresh_from_db()
    revised_batch = settlement.settlement_approval

    assert first_batch.status == first_batch.Status.SUPERSEDED
    assert first_batch.items.get().item_status == PaymentApprovalItem.Status.SUPERSEDED
    assert revised_batch.revision_no == 2
    assert revised_batch.supersedes_id == first_batch.pk
    assert any(change["field"] == "final_freight" for change in revised_batch.revision_diff)


@pytest.mark.django_db
def test_returned_advance_creates_a_superseding_revision(trip_factory, users):
    trip = trip_factory(1)
    operations = users[User.Role.OPERATIONS]
    first_batch = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=first_batch, actor=operations)
    decide_batch(
        batch=first_batch,
        actor=users[User.Role.APPROVER],
        decision=ApprovalAction.Action.SEND_BACK,
        comment="Correct the contracted rate.",
    )
    client = APIClient()
    client.force_authenticate(operations)
    revised = client.post(
        f"/api/trips/{trip.pk}/revise/",
        {"reason": "Updated vendor contract", "vendor_freight_rate": "51000.00"},
        format="json",
    )
    assert revised.status_code == 200

    second_batch = create_approval_batch(actor=operations, trips=[trip])
    first_batch.refresh_from_db()
    assert first_batch.status == first_batch.Status.SUPERSEDED
    assert first_batch.items.get().item_status == PaymentApprovalItem.Status.SUPERSEDED
    assert second_batch.revision_no == 2
    assert second_batch.supersedes_id == first_batch.pk
    assert any(
        change["field"] == "vendor_freight_rate" for change in second_batch.revision_diff
    )


@pytest.mark.django_db
def test_paid_trip_cancellation_opens_and_resolves_recovery(trip_factory, users):
    trip = trip_factory(1)
    payment = _approved_advance_payment(trip, users, "CANCEL-ADVANCE")
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    cancelled = client.post(
        f"/api/trips/{trip.pk}/cancel/",
        {
            "resolution_method": TripRecovery.Resolution.REFUND,
            "reason": "Client cancelled after dispatch.",
        },
        format="json",
    )
    assert cancelled.status_code == 200
    trip.refresh_from_db()
    recovery = trip.recovery
    assert trip.status == Trip.Status.CANCELLED_WITH_PAYMENT
    assert recovery.amount == payment.net_paid_amount
    assert recovery.status == "OPEN"

    resolved = client.post(
        f"/api/recoveries/{recovery.pk}/resolve/",
        {"reference": "REFUND-2026-001"},
        format="json",
    )
    assert resolved.status_code == 200
    recovery.refresh_from_db()
    assert recovery.status == "RESOLVED"
    assert recovery.resolved_by == users[User.Role.OPERATIONS]


@pytest.mark.django_db
def test_transporter_only_sees_own_vendor_recoveries(trip_factory, users):
    own_trip = trip_factory(1)
    other_trip = trip_factory(2)
    TripRecovery.objects.create(
        trip=own_trip,
        amount=Decimal("100.00"),
        resolution_method=TripRecovery.Resolution.REFUND,
        reason="Own recovery",
        created_by=users[User.Role.OPERATIONS],
    )
    TripRecovery.objects.create(
        trip=other_trip,
        amount=Decimal("200.00"),
        resolution_method=TripRecovery.Resolution.REFUND,
        reason="Other recovery",
        created_by=users[User.Role.OPERATIONS],
    )
    transporter = User.objects.create_user(
        username="transporter-recovery",
        password="StrongPass123!",
        role=User.Role.TRANSPORTER,
        vendor=own_trip.vendor,
    )
    client = APIClient()
    client.force_authenticate(transporter)

    response = client.get("/api/recoveries/")
    assert response.status_code == 200
    assert [row["trip"] for row in response.data["results"]] == [own_trip.pk]


@pytest.mark.django_db
def test_paid_and_reversed_transactions_are_immutable(trip_factory, users):
    trip = trip_factory(1)
    payment = _approved_advance_payment(trip, users, "IMMUTABLE-ADVANCE")

    payment.status = FinancePaymentTransaction.Status.FAILED
    with pytest.raises(ValidationError, match="only transition to reversed"):
        payment.save()

    payment.refresh_from_db()
    payment.remarks = "Silently changed"
    with pytest.raises(ValidationError, match="immutable"):
        payment.save()

    payment.refresh_from_db()
    payment.status = FinancePaymentTransaction.Status.REVERSED
    with pytest.raises(ValidationError, match="reversal reason"):
        payment.save()

    payment.refresh_from_db()
    reverse_payment(
        actor=users[User.Role.FINANCE],
        payment=payment,
        reason="Bank returned the transfer.",
    )
    payment.refresh_from_db()
    allocation = payment.allocations.get()
    allocation.net_cash_allocated -= Decimal("1.00")
    with pytest.raises(ValidationError, match="allocations are immutable"):
        allocation.save()

    trip.refresh_from_db()
    assert trip.status == Trip.Status.ADVANCE_APPROVED
    client = APIClient()
    client.force_authenticate(users[User.Role.FINANCE])
    ledger = client.get(f"/api/vendor-ledger/{trip.vendor_id}/")
    assert ledger.status_code == 200
    assert Decimal(ledger.data["cash_paid"]) == 0
    assert [entry["type"] for entry in ledger.data["entries"]] == [
        "PAYMENT",
        "PAYMENT_REVERSAL",
    ]


@pytest.mark.django_db
def test_whatsapp_status_webhook_is_idempotent(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    message = IntegrationMessage.objects.create(
        channel=IntegrationMessage.Channel.WHATSAPP,
        direction="OUTBOUND",
        idempotency_key="wa-status-outbound",
        external_message_id="wamid-status-1",
        object_type="payment",
        object_id="1",
        status="SENT",
    )
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {"id": "wamid-status-1", "status": "read", "timestamp": "1"}
                            ]
                        }
                    }
                ]
            }
        ]
    }
    client = APIClient()
    assert client.post("/api/webhooks/whatsapp/", payload, format="json").status_code == 200
    assert client.post("/api/webhooks/whatsapp/", payload, format="json").status_code == 200
    message.refresh_from_db()
    assert message.status == "READ"
    assert IntegrationMessage.objects.filter(external_message_id="wamid-status-1").count() == 1


@pytest.mark.django_db
def test_whatsapp_media_is_validated_and_attached(monkeypatch, trip_factory, users):
    trip = trip_factory(1)
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    message = IntegrationMessage.objects.create(
        channel=IntegrationMessage.Channel.WHATSAPP,
        direction="INBOUND",
        idempotency_key="wa-media-inbound",
        external_message_id="wamid-media-1",
        object_type="approval",
        object_id=str(batch.pk),
        status="RECEIVED",
    )
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(
        "integrations.services.request_json",
        lambda *args, **kwargs: {"url": "https://media.test/file", "mime_type": "image/png"},
    )
    monkeypatch.setattr(
        "integrations.services.download_binary",
        lambda *args, **kwargs: (b"\x89PNG\r\n\x1a\nvalidated", "image/png"),
    )

    document = persist_whatsapp_media(message, {"id": "media-1", "filename": "proof.png"})
    message.refresh_from_db()
    assert document.scan_status == "CLEAN"
    assert document.uploaded_by == users[User.Role.OPERATIONS]
    assert message.raw_metadata["attachment_id"] == document.pk


@pytest.mark.django_db
def test_channel_specific_notification_template_is_rendered():
    NotificationTemplate.objects.create(
        event_key="PAYMENT_COMPLETED",
        channel=IntegrationMessage.Channel.EMAIL,
        subject_template="Payment {reference}",
        body_template="Vendor {vendor} received net {net}",
    )
    subject, body = render_event(
        "PAYMENT_COMPLETED",
        {"reference": "PAY-1", "vendor": "North Star", "net": "990.00"},
        channel=IntegrationMessage.Channel.EMAIL,
    )
    assert subject == "Payment PAY-1"
    assert body == "Vendor North Star received net 990.00"
