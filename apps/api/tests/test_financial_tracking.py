from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from approvals.models import ApprovalAction
from approvals.services import create_approval_batch, decide_batch, submit_batch
from core.crypto import encrypt_value
from operations.models import Document, VendorBankAccount
from payments.services import create_paid_payment


def clean_document(*, actor, object_type, object_id, kind, name):
    return Document.objects.create(
        object_type=object_type,
        object_id=str(object_id),
        kind=kind,
        file=ContentFile(b"%PDF-1.4\n", name=name),
        original_name=name,
        content_type="application/pdf",
        size=9,
        sha256=name.encode().hex().ljust(64, "0")[:64],
        scan_status="CLEAN",
        uploaded_by=actor,
    )


@pytest.mark.django_db
def test_finance_queue_contains_payment_due_diligence_without_full_account_number(trip_factory, users, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    trip = trip_factory(1)
    bank = VendorBankAccount.objects.create(
        vendor=trip.vendor,
        bank_name="HDFC Bank",
        account_holder=trip.vendor.legal_name,
        account_number_encrypted=encrypt_value("123456789012"),
        account_last_four="9012",
        ifsc_code="HDFC0001234",
    )
    clean_document(actor=users[User.Role.OPERATIONS], object_type="vendor", object_id=trip.vendor_id, kind=Document.Kind.AADHAAR, name="vendor-aadhaar.pdf")
    clean_document(actor=users[User.Role.OPERATIONS], object_type="driver", object_id=trip.driver_id, kind=Document.Kind.DRIVING_LICENSE, name="driver-dl.pdf")
    clean_document(actor=users[User.Role.OPERATIONS], object_type="trip", object_id=trip.pk, kind=Document.Kind.LR, name="lr.pdf")
    clean_document(actor=users[User.Role.OPERATIONS], object_type="vendor_bank_account", object_id=bank.pk, kind=Document.Kind.CANCELLED_CHEQUE, name="cancelled-cheque.pdf")

    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)

    client = APIClient()
    client.force_authenticate(users[User.Role.FINANCE])
    response = client.get("/api/finance/pending/")

    assert response.status_code == 200
    group = response.data[0]
    item = group["items"][0]
    assert group["bank_accounts"][0]["masked_account_number"] == "•••• 9012"
    assert "123456789012" not in str(response.data)
    assert group["bank_accounts"][0]["cancelled_cheque_documents"][0]["kind"] == "CANCELLED_CHEQUE"
    assert group["vendor_documents"][0]["kind"] == "AADHAAR"
    assert item["driver_documents"][0]["kind"] == "DRIVING_LICENSE"
    assert item["trip_documents"][0]["kind"] == "LR"
    assert Decimal(item["freight_100"]) == Decimal("50000.00")
    assert Decimal(item["advance_amount"]) == Decimal("45000.00")
    assert Decimal(item["freight_balance_after_advance"]) == Decimal("5000.00")
    assert item["approved_at"] is not None


@pytest.mark.django_db
def test_dashboard_and_ledgers_share_cash_tds_and_remaining_formula(trip_factory, users):
    trip = trip_factory(1)
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)
    item = batch.items.get()
    create_paid_payment(
        actor=users[User.Role.FINANCE],
        vendor=trip.vendor,
        payment_date=timezone.localdate(),
        utr_reference="FIN-TRACK-001",
        allocations=[{
            "approval_item_id": item.pk,
            "gross_amount_allocated": item.gross_requested,
            "tds_allocated": item.tds_this_request,
            "net_cash_allocated": item.net_requested,
        }],
    )

    client = APIClient()
    client.force_authenticate(users[User.Role.FINANCE])
    dashboard = client.get("/api/dashboard/").data
    vendor_ledger = client.get(f"/api/vendor-ledger/{trip.vendor_id}/").data
    trip_ledger = client.get(f"/api/trip-ledger/{trip.pk}/").data

    for data in (dashboard, vendor_ledger):
        assert Decimal(data["total_freight_100"]) == Decimal("50000.00")
        assert Decimal(data["total_advance_amount"]) == Decimal("45000.00")
        assert Decimal(data["freight_balance_after_advance"]) == Decimal("5000.00")
    assert Decimal(dashboard["total_cash_paid"]) == Decimal("47050.00")
    assert Decimal(dashboard["total_tds_deducted"]) == Decimal("450.00")
    assert Decimal(dashboard["total_remaining_to_pay"]) == Decimal("2500.00")
    assert Decimal(vendor_ledger["remaining_to_pay"]) == Decimal("2500.00")
    assert Decimal(trip_ledger["remaining_to_pay"]) == Decimal("2500.00")
    assert trip_ledger["created_at"] is not None
    assert vendor_ledger["entries"][0]["timestamp"] is not None
