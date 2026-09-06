"""Regression tests for defects found in the September 2026 code review."""

import pytest
from django.utils import timezone

from accounts.models import User
from approvals.models import Comment
from approvals.services import create_approval_batch, decide_batch, submit_batch
from integrations.services import ingest_email_reply, queue_message
from operations.models import Trip
from payments.services import reverse_payment
from tests.test_lifecycle_regressions import approval, client_for, payment


@pytest.mark.django_db
def test_revision_diff_reports_only_changed_fields(trip_factory, users):
    trip = trip_factory()
    batch = approval(trip, users, approve=False)
    decide_batch(actor=users[User.Role.APPROVER], batch=batch, decision="SEND_BACK", comment="Lower the advance")
    response = client_for(users[User.Role.OPERATIONS]).post(
        f"/api/trips/{trip.pk}/revise/", {"advance_percent": "80", "reason": "Approver asked"}, format="json"
    )
    assert response.status_code == 200, response.data
    revision = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    fields = {row["field"]: row for row in revision.revision_diff}
    assert fields["advance_percent"]["old"] == "90.00"
    assert fields["advance_percent"]["new"] == "80.00"
    assert "vendor_freight_rate" not in fields, "unchanged freight must not appear as a phantom change"


@pytest.mark.django_db
@pytest.mark.parametrize("decision", ["APPROVE", "REJECT"])
def test_decisions_never_rewind_a_delivered_trip(trip_factory, users, decision):
    trip = trip_factory()
    batch = approval(trip, users, approve=False)
    assert client_for(users[User.Role.OPERATIONS]).post(f"/api/trips/{trip.pk}/deliver/", {}, format="json").status_code == 200
    decide_batch(actor=users[User.Role.APPROVER], batch=batch, decision=decision, comment="Decided after delivery")
    trip.refresh_from_db()
    assert trip.status == Trip.Status.DELIVERED


@pytest.mark.django_db
def test_cancelling_a_trip_closes_its_pending_line_so_the_batch_can_finish(trip_factory, users):
    first, second = trip_factory(1), trip_factory(2)
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[first, second])
    submit_batch(actor=users[User.Role.OPERATIONS], batch=batch)
    assert client_for(users[User.Role.OPERATIONS]).post(f"/api/trips/{first.pk}/cancel/", {}, format="json").status_code == 200
    batch.refresh_from_db()
    assert batch.items.get(trip=first).item_status == "SUPERSEDED"
    assert batch.items.get(trip=second).item_status == "PENDING"
    decide_batch(actor=users[User.Role.APPROVER], batch=batch, decision="APPROVE")
    batch.refresh_from_db()
    assert batch.status == "APPROVED"


@pytest.mark.django_db
def test_reversal_is_refused_on_settled_trips(trip_factory, users):
    trip = trip_factory()
    batch = approval(trip, users)
    paid = payment(batch.items.get(), users)
    trip.status = Trip.Status.SETTLED
    trip.save(update_fields=["status", "updated_at"])
    with pytest.raises(ValueError, match="settled"):
        reverse_payment(payment=paid, actor=users[User.Role.FINANCE], reason="Wrong vendor")
    paid.refresh_from_db()
    assert paid.status == "PAID"


@pytest.mark.django_db
def test_email_reply_without_a_thread_id_stays_unmapped(trip_factory, users):
    trip = trip_factory()
    batch = approval(trip, users, approve=False)
    queue_message(
        channel="EMAIL",
        recipient="approver@example.com",
        subject=f"Approval {batch.approval_no}",
        body="Please review",
        object_type="approval",
        object_id=batch.pk,
        idempotency_key=f"test-outbound-{batch.pk}",
    )
    inbound = ingest_email_reply(
        external_message_id="inbound-1", external_thread_id="", subject="Re: something else", body="Looks fine", sender="vendor@example.com"
    )
    assert inbound.object_type == "unmapped"
    assert not Comment.objects.filter(object_type="approval", object_id=str(batch.pk)).exists()


@pytest.mark.django_db
def test_comment_binding_and_visibility_are_fixed_after_posting(trip_factory, users):
    trip = trip_factory()
    client = client_for(users[User.Role.OPERATIONS])
    created = client.post(
        "/api/comments/", {"object_type": "trip", "object_id": str(trip.pk), "body": "Internal note"}, format="json"
    )
    assert created.status_code == 201, created.data
    flipped = client.patch(f"/api/comments/{created.data['id']}/", {"visibility": "TRANSPORTER_VISIBLE"}, format="json")
    assert flipped.status_code == 400
    moved = client.patch(f"/api/comments/{created.data['id']}/", {"object_id": "999999"}, format="json")
    assert moved.status_code == 400
    edited = client.patch(f"/api/comments/{created.data['id']}/", {"body": "Internal note (clarified)"}, format="json")
    assert edited.status_code == 200, edited.data


@pytest.mark.django_db
def test_global_search_scopes_transporters_before_truncating(trip_factory, users):
    trips = [trip_factory(index) for index in range(1, 13)]
    own = trips[0]
    transporter = User.objects.create_user(username="transporter-search", password="StrongPass123!", role="TRANSPORTER", vendor=own.vendor)
    response = client_for(transporter).get("/api/search/?q=Sonipat")
    assert response.status_code == 200
    found = [row for row in response.data["results"] if row["type"] == "trip"]
    assert [row["id"] for row in found] == [own.pk]


@pytest.mark.django_db
def test_document_links_are_relative_for_the_web_proxy(trip_factory, users):
    from django.core.files.uploadedfile import SimpleUploadedFile

    trip = trip_factory()
    client = client_for(users[User.Role.OPERATIONS])
    upload = client.post(
        "/api/documents/",
        {"file": SimpleUploadedFile("pod.pdf", b"%PDF-1.4\n", content_type="application/pdf"), "kind": "POD", "object_type": "trip", "object_id": trip.pk},
        format="multipart",
    )
    assert upload.status_code == 201, upload.data
    assert upload.data["download_url"].startswith("/api/documents/"), upload.data["download_url"]
    assert timezone.now()  # keeps the import used for future date assertions


@pytest.mark.django_db
def test_email_reply_from_unknown_sender_stays_unmapped_even_with_approval_reference(trip_factory, users):
    batch = approval(trip_factory(), users, approve=False)
    inbound = ingest_email_reply(
        external_message_id="spoof-1",
        external_thread_id="",
        subject=f"Re: [{batch.approval_no}] Please approve",
        body="I am not a vendor contact",
        sender="attacker@example.test",
    )
    assert inbound.object_type == "unmapped"
    assert not Comment.objects.filter(object_type="approval", object_id=str(batch.pk)).exists()
