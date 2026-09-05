import pytest
from rest_framework.test import APIClient

from accounts.models import User
from approvals.models import PaymentApprovalBatch
from core.crypto import encrypt_value
from operations.models import Client


@pytest.mark.django_db
@pytest.mark.parametrize("path,content_type", [
    ("/api/mis/records/?format=xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("/api/reports/trip-cost-payment/?format=csv", "text/csv"),
])
def test_export_format_does_not_trigger_renderer_404(users, path, content_type):
    response = authenticated(users, User.Role.ADMIN).get(path)
    assert response.status_code == 200, getattr(response, "data", None)
    assert response["Content-Type"].startswith(content_type)


def authenticated(users, role=User.Role.OPERATIONS):
    client = APIClient()
    client.force_authenticate(users[role])
    return client


@pytest.mark.django_db
def test_password_policy_failure_is_a_validation_response(users):
    client = authenticated(users)
    response = client.post("/api/auth/password/change/", {
        "current_password": "StrongPass123!", "new_password": "1234567890123",
    }, format="json")
    assert response.status_code == 400
    users[User.Role.OPERATIONS].refresh_from_db()
    assert users[User.Role.OPERATIONS].check_password("StrongPass123!")


@pytest.mark.django_db
def test_mfa_setup_cannot_disable_existing_mfa(users):
    user = users[User.Role.OPERATIONS]
    secret = encrypt_value("JBSWY3DPEHPK3PXP")
    user.mfa_enabled = True
    user.mfa_secret_encrypted = secret
    user.save()
    response = authenticated(users).post("/api/auth/mfa/setup/", {}, format="json")
    assert response.status_code == 400
    user.refresh_from_db()
    assert user.mfa_enabled
    assert user.mfa_secret_encrypted == secret


@pytest.mark.django_db
@pytest.mark.parametrize("missing", [True, False])
def test_approval_rejects_missing_or_duplicate_trip_ids(trip_factory, users, missing):
    trip = trip_factory()
    ids = [trip.pk, trip.pk + 1000 if missing else trip.pk]
    response = authenticated(users).post("/api/approval-batches/", {"trip_ids": ids}, format="json")
    assert response.status_code == 400
    assert not PaymentApprovalBatch.objects.exists()


@pytest.mark.django_db
def test_list_pagination_honors_page_size(users):
    Client.objects.bulk_create([Client(code=f"C{i}", name=f"Client {i}") for i in range(55)])
    client = authenticated(users)
    response = client.get("/api/clients/?page_size=25")
    assert len(response.data["results"]) == 25
    second = client.get("/api/clients/?page_size=25&page=2")
    assert len(second.data["results"]) == 25
    assert not ({row["id"] for row in response.data["results"]} & {row["id"] for row in second.data["results"]})
    assert len(client.get("/api/clients/?page_size=200").data["results"]) == 55


@pytest.mark.django_db
def test_operations_cannot_manually_mark_trip_paid(trip_factory, users):
    trip = trip_factory()
    response = authenticated(users).patch(f"/api/trips/{trip.pk}/", {"status": "ADVANCE_PAID"}, format="json")
    assert response.status_code == 400
    trip.refresh_from_db()
    assert trip.status == "READY"


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["-1", "101"])
def test_trip_advance_percentage_is_bounded(trip_factory, users, value):
    trip = trip_factory()
    response = authenticated(users).patch(f"/api/trips/{trip.pk}/", {"advance_percent": value}, format="json")
    assert response.status_code == 400
    assert "advance_percent" in response.data


@pytest.mark.django_db
def test_settlement_patch_validates_decimal_inputs(trip_factory, users):
    from payments.services import save_settlement

    trip = trip_factory()
    trip.status = "DELIVERED"
    trip.save()
    settlement = save_settlement(actor=users[User.Role.OPERATIONS], trip=trip, final_freight="50000")
    response = authenticated(users).patch(f"/api/settlements/{settlement.pk}/", {"final_freight": "not-a-number"}, format="json")
    assert response.status_code == 400
    assert "final_freight" in response.data
    settlement.refresh_from_db()
    assert settlement.final_freight == 50000


@pytest.mark.django_db
def test_duplicate_payment_allocations_are_rejected_before_posting(trip_factory, users):
    from django.utils import timezone

    from approvals.services import create_approval_batch, decide_batch, submit_batch
    from payments.models import FinancePaymentTransaction
    from payments.services import create_paid_payment

    trip = trip_factory()
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision="APPROVE")
    item = batch.items.get()
    entry = {"approval_item_id": item.pk, "gross_amount_allocated": item.gross_requested,
             "tds_allocated": item.tds_this_request, "net_cash_allocated": item.net_requested}
    with pytest.raises(ValueError, match="only once"):
        create_paid_payment(actor=users[User.Role.FINANCE], vendor=trip.vendor, payment_date=timezone.localdate(),
                            utr_reference="DUP-TEST", allocations=[entry, entry])
    assert not FinancePaymentTransaction.objects.exists()


@pytest.mark.django_db
def test_trip_and_initial_unloading_are_saved_together(trip_factory, users, monkeypatch):
    from operations.models import Trip, TripCharge

    existing = trip_factory()
    client = authenticated(users)
    payload = {
        "client": existing.client_id, "indent": existing.indent_id,
        "indent_ids": [existing.indent_id], "vendor": existing.vendor_id,
        "vehicle": existing.vehicle_id, "driver": existing.driver_id,
        "origin": "Sonipat", "destination": "Delhi", "deployment_date": "2026-09-05",
        "vendor_freight_rate": "5000.00", "unloading_advance": "1500.00",
    }
    original_create = TripCharge.objects.create

    def fail_charge(**kwargs):
        raise ValueError("Charge could not be saved")

    monkeypatch.setattr(TripCharge.objects, "create", fail_charge)
    failed = client.post("/api/trips/", payload, format="json")
    assert failed.status_code == 400
    assert Trip.objects.count() == 1
    monkeypatch.setattr(TripCharge.objects, "create", original_create)
    success = client.post("/api/trips/", payload, format="json")
    assert success.status_code == 201, success.data
    assert success.data["calculation"]["gross_requested"] == "6000.00"
    assert Trip.objects.count() == 2
    assert Trip.objects.get(pk=success.data["id"]).charges.get().amount == 1500
