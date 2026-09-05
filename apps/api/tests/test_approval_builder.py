import pytest
from rest_framework.test import APIClient

from accounts.models import User
from approvals.services import create_approval_batch
from approvals.models import PaymentApprovalBatch
from operations.models import Trip


@pytest.mark.django_db
def test_builder_financial_patch(trip_factory, users):
    trip = trip_factory()
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])
    response = client.patch(
        f"/api/trips/{trip.pk}/",
        {"vendor_freight_rate": "5000.00", "advance_percent": "90.00"},
        format="json",
    )
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_builder_cannot_edit_existing_draft_snapshot(trip_factory, users):
    trip = trip_factory()
    create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])
    response = client.patch(
        f"/api/trips/{trip.pk}/",
        {"vendor_freight_rate": str(trip.vendor_freight_rate), "advance_percent": str(trip.advance_percent)},
        format="json",
    )
    assert response.status_code == 400
    assert "active approval snapshot" in str(response.data)

    listing = client.get("/api/trips/?status=READY")
    row = listing.data["results"][0]
    draft = PaymentApprovalBatch.objects.get()
    assert row["active_approval"]["id"] == draft.pk
    duplicate = client.post("/api/approval-batches/", {"trip_ids": [trip.pk], "submit": True}, format="json")
    assert duplicate.status_code == 400
    assert draft.approval_no in str(duplicate.data)
    assert PaymentApprovalBatch.objects.count() == 1
    resumed = client.post(f"/api/approval-batches/{draft.pk}/submit/", {}, format="json")
    assert resumed.status_code == 200, resumed.data
    assert resumed.data["status"] == "PENDING"


@pytest.mark.django_db
def test_create_and_submit_is_atomic(trip_factory, users, monkeypatch):
    trip = trip_factory()
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])

    from approvals import views
    original_submit = views.submit_batch

    def fail_submission(**kwargs):
        original_submit(**kwargs)
        raise ValueError("Submission temporarily unavailable")

    monkeypatch.setattr(views, "submit_batch", fail_submission)
    failed = client.post("/api/approval-batches/", {"trip_ids": [trip.pk], "submit": True}, format="json")
    assert failed.status_code == 400
    assert not PaymentApprovalBatch.objects.exists()
    assert not trip.approval_items.exists()
    trip.refresh_from_db()
    assert trip.status == Trip.Status.READY

    monkeypatch.setattr(views, "submit_batch", original_submit)
    retry = client.post("/api/approval-batches/", {"trip_ids": [trip.pk], "submit": True}, format="json")
    assert retry.status_code == 201, retry.data
    assert retry.data["status"] == "PENDING"
    trip.refresh_from_db()
    assert trip.status == Trip.Status.ADVANCE_APPROVAL_PENDING
    duplicate = client.post("/api/approval-batches/", {"trip_ids": [trip.pk], "submit": True}, format="json")
    assert duplicate.status_code == 400
    assert PaymentApprovalBatch.objects.count() == 1


@pytest.mark.django_db
def test_another_requester_cannot_open_or_submit_draft(trip_factory, users):
    trip = trip_factory()
    draft = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    other = User.objects.create_user(username="other_ops", role=User.Role.OPERATIONS)
    client = APIClient()
    client.force_authenticate(other)
    listing = client.get("/api/trips/?status=READY")
    assert listing.data["results"][0]["active_approval"]["id"] is None
    response = client.post(f"/api/approval-batches/{draft.pk}/submit/", {}, format="json")
    assert response.status_code == 404
