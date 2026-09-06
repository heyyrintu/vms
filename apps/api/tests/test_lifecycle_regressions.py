import hashlib
import json
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from approvals.services import create_approval_batch, decide_batch, submit_batch
from audit.models import AuditLog, record_audit
from integrations.models import IntegrationMessage
from payments.models import FinancePaymentTransaction
from payments.services import create_paid_payment, reverse_payment


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def approval(trip, users, approve=True):
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(actor=users[User.Role.OPERATIONS], batch=batch)
    if approve:
        decide_batch(actor=users[User.Role.APPROVER], batch=batch, decision="APPROVE")
    return batch


def payment(item, users, net=None, tds=None, reference="LIFECYCLE-TEST"):
    net = item.net_requested if net is None else Decimal(net)
    tds = item.tds_this_request if tds is None else Decimal(tds)
    return create_paid_payment(
        actor=users[User.Role.FINANCE], vendor=item.vendor, payment_date=timezone.localdate(),
        utr_reference=reference, notify=False,
        allocations=[{"approval_item_id": item.pk, "gross_amount_allocated": net + tds,
                      "tds_allocated": tds, "net_cash_allocated": net}],
    )


@pytest.mark.django_db
def test_delivery_records_timestamp_audit_and_notification_once(trip_factory, users):
    trip = trip_factory()
    client = client_for(users[User.Role.OPERATIONS])
    response = client.post(f"/api/trips/{trip.pk}/deliver/", {}, format="json")
    assert response.status_code == 200, response.data
    trip.refresh_from_db()
    delivered_at = trip.actual_delivery_at
    audit = AuditLog.objects.get(action="TRIP_DELIVERED", object_id=str(trip.pk))
    assert audit.after["actual_delivery_at"] == str(delivered_at)
    assert IntegrationMessage.objects.filter(event_key="SETTLEMENT_PENDING", object_id=str(trip.pk)).exists()
    assert client.post(f"/api/trips/{trip.pk}/deliver/", {}, format="json").status_code == 200
    trip.refresh_from_db()
    assert trip.actual_delivery_at == delivered_at
    assert AuditLog.objects.filter(action="TRIP_DELIVERED", object_id=str(trip.pk)).count() == 1


@pytest.mark.django_db
def test_delivery_rolls_back_when_audit_fails(trip_factory, users, monkeypatch):
    trip = trip_factory()

    def fail_audit(**kwargs):
        raise ValueError("Audit unavailable")

    monkeypatch.setattr("operations.views.record_audit", fail_audit)
    response = client_for(users[User.Role.OPERATIONS]).post(f"/api/trips/{trip.pk}/deliver/", {}, format="json")
    assert response.status_code == 400
    trip.refresh_from_db()
    assert trip.status == "READY"
    assert trip.actual_delivery_at is None


@pytest.mark.django_db
def test_audit_hash_matches_serialized_values(trip_factory, users):
    trip = trip_factory()
    entry = record_audit(actor=users[User.Role.OPERATIONS], action="TYPED_VALUES", instance=trip,
                         after={"at": timezone.now(), "amount": Decimal("10.00")})
    entry.refresh_from_db()
    payload = {key: getattr(entry, key) for key in ["action", "object_type", "object_id", "before", "after", "request_id", "source", "previous_hash"]}
    payload["actor"] = entry.actor_id
    assert entry.entry_hash == hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["APPROVE", "REJECT", "SEND_BACK"])
def test_cancelled_trip_cannot_be_revived_by_decision(trip_factory, users, decision):
    trip = trip_factory()
    batch = approval(trip, users, approve=False)
    client = client_for(users[User.Role.OPERATIONS])
    assert client.post(f"/api/trips/{trip.pk}/cancel/", {}, format="json").status_code == 200
    batch.refresh_from_db()
    with pytest.raises(ValueError):
        decide_batch(actor=users[User.Role.APPROVER], batch=batch, decision=decision, comment="Test decision")
    trip.refresh_from_db()
    assert trip.status == "CANCELLED"
    # The line is closed so the batch cannot stay pending forever.
    assert batch.items.get().item_status == "SUPERSEDED"
    assert batch.status != "PENDING"


@pytest.mark.django_db
def test_cancelled_draft_cannot_submit(trip_factory, users):
    trip = trip_factory()
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    client_for(users[User.Role.OPERATIONS]).post(f"/api/trips/{trip.pk}/cancel/", {}, format="json")
    with pytest.raises(ValueError, match="Cancelled"):
        submit_batch(actor=users[User.Role.OPERATIONS], batch=batch)
    batch.refresh_from_db()
    assert batch.status == "DRAFT"


@pytest.mark.django_db
def test_cancelled_approved_trip_cannot_be_paid(trip_factory, users):
    trip = trip_factory()
    batch = approval(trip, users)
    client_for(users[User.Role.OPERATIONS]).post(f"/api/trips/{trip.pk}/cancel/", {}, format="json")
    assert client_for(users[User.Role.FINANCE]).get("/api/finance/pending/").data == []
    with pytest.raises(ValueError, match="cancelled"):
        payment(batch.items.get(), users)
    assert not FinancePaymentTransaction.objects.exists()


@pytest.mark.django_db
def test_returned_approval_requires_revision_with_current_amounts(trip_factory, users):
    trip = trip_factory()
    batch = approval(trip, users, approve=False)
    decide_batch(actor=users[User.Role.APPROVER], batch=batch, decision="SEND_BACK", comment="Correct freight")
    client = client_for(users[User.Role.OPERATIONS])
    assert client.patch(f"/api/trips/{trip.pk}/", {"vendor_freight_rate": "60000.00"}, format="json").status_code == 200
    response = client.post(f"/api/approval-batches/{batch.pk}/submit/", {}, format="json")
    assert response.status_code == 400
    assert "revision" in str(response.data)
    assert batch.items.get().freight_rate_snapshot == Decimal("50000.00")
    revised = client.post("/api/approval-batches/", {"trip_ids": [trip.pk], "submit": True}, format="json")
    assert revised.status_code == 201, revised.data
    assert revised.data["revision_no"] == 2
    assert revised.data["status"] == "PENDING"
    assert revised.data["items"][0]["freight_rate_snapshot"] == "60000.00"


@pytest.mark.django_db
def test_tds_only_balance_remains_payable(trip_factory, users):
    trip = trip_factory()
    item = approval(trip, users).items.get()
    payment(item, users, tds="0")
    client = client_for(users[User.Role.FINANCE])
    trip.refresh_from_db()
    assert trip.status == "ADVANCE_PARTIALLY_PAID"
    row = client.get("/api/finance/pending/").data[0]["items"][0]
    assert Decimal(row["remaining_net"]) == 0
    assert Decimal(row["remaining_tds"]) == item.tds_this_request
    payment(item, users, net="0", reference="TDS-ONLY")
    trip.refresh_from_db()
    assert trip.status == "ADVANCE_PAID"
    assert client.get("/api/finance/pending/").data == []


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["DEPLOYED", "IN_TRANSIT", "DELIVERED", "SETTLEMENT_PENDING"])
def test_advance_reversal_preserves_operational_status(trip_factory, users, status):
    trip = trip_factory()
    item = approval(trip, users).items.get()
    paid = payment(item, users)
    trip.refresh_from_db()
    trip.status = status
    trip.actual_delivery_at = timezone.now() if status in {"DELIVERED", "SETTLEMENT_PENDING"} else None
    delivered_at = trip.actual_delivery_at
    trip.save()
    reverse_payment(actor=users[User.Role.FINANCE], payment=paid, reason="Bank returned transfer")
    trip.refresh_from_db()
    assert trip.status == status
    assert trip.actual_delivery_at == delivered_at
    # Reposting a late advance must not erase the lifecycle either.
    payment(item, users, reference="REPLACEMENT")
    trip.refresh_from_db()
    assert trip.status == status
