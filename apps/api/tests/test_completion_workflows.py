import json
import time
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.mfa import _code
from accounts.models import User
from approvals.models import ApprovalAction, ApprovalRule, ApprovalStage, Comment
from approvals.services import create_approval_batch, decide_batch, submit_batch
from core.crypto import decrypt_value
from imports.models import ImportJob
from imports.services import confirm_import
from integrations.models import IntegrationMessage
from integrations.services import emit_event, queue_message
from operations.models import Client, Document, Trip
from payments.models import ClientBilling
from payments.reports import REPORT_CATALOG, build_report, export_csv, export_xlsx
from payments.services import (
    create_paid_payment,
    finalize_settlement,
    save_settlement,
    submit_settlement,
)


@pytest.mark.django_db
def test_sequential_approval_rule_enforces_each_role(trip_factory, users):
    trip = trip_factory(1)
    rule = ApprovalRule.objects.create(name="Two stage", min_amount=0, purpose="ADVANCE")
    ApprovalStage.objects.create(rule=rule, sequence=1, role=User.Role.APPROVER, label="Manager")
    ApprovalStage.objects.create(rule=rule, sequence=2, role=User.Role.FINANCE, label="Finance")
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])

    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)
    batch.refresh_from_db()
    assert batch.current_stage == 2
    assert batch.status == batch.Status.PENDING
    assert batch.items.get().item_status == "PENDING"

    with pytest.raises(PermissionError, match="FINANCE"):
        decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)
    decide_batch(batch=batch, actor=users[User.Role.FINANCE], decision=ApprovalAction.Action.APPROVE)
    batch.refresh_from_db()
    assert batch.status == batch.Status.APPROVED


@pytest.mark.django_db
def test_document_upload_is_scanned_and_updates_pod(trip_factory, users):
    trip = trip_factory(1)
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])
    response = client.post(
        "/api/documents/",
        {
            "object_type": "trip",
            "object_id": str(trip.pk),
            "kind": "POD",
            "file": SimpleUploadedFile("pod.pdf", b"%PDF-1.4\n%test", content_type="application/pdf"),
        },
        format="multipart",
    )
    assert response.status_code == 201
    assert response.data["scan_status"] == "CLEAN"
    trip.refresh_from_db()
    assert trip.pod_status == "RECEIVED"

    rejected = client.post(
        "/api/documents/",
        {
            "object_type": "trip",
            "object_id": str(trip.pk),
            "kind": "OTHER",
            "file": SimpleUploadedFile("bad.pdf", b"not a pdf", content_type="application/pdf"),
        },
        format="multipart",
    )
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_mentions_create_notifications_and_edits_preserve_history(trip_factory, users):
    trip = trip_factory(1)
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])
    created = client.post(
        "/api/comments/",
        {
            "object_type": "trip",
            "object_id": str(trip.pk),
            "body": "Please review this rate.",
            "visibility": "INTERNAL",
            "mentions": [users[User.Role.APPROVER].pk],
        },
        format="json",
    )
    assert created.status_code == 201
    assert IntegrationMessage.objects.filter(
        channel="IN_APP", user=users[User.Role.APPROVER], event_key="MENTION"
    ).exists()
    edited = client.patch(
        f"/api/comments/{created.data['id']}/",
        {"body": "Please review the corrected rate."},
        format="json",
    )
    assert edited.status_code == 200
    comment = Comment.objects.get(pk=created.data["id"])
    assert comment.edit_history[0]["body"] == "Please review this rate."
    assert comment.edited_at is not None


def _document(trip, actor, kind, name):
    return Document.objects.create(
        object_type="trip",
        object_id=str(trip.pk),
        kind=kind,
        file=ContentFile(b"%PDF-1.4\n", name=name),
        original_name=name,
        content_type="application/pdf",
        size=9,
        sha256=("a" if kind == "POD" else "b") * 64,
        scan_status="CLEAN",
        uploaded_by=actor,
    )


@pytest.mark.django_db
def test_final_settlement_approval_payment_billing_and_close(trip_factory, users):
    trip = trip_factory(1)
    operations = users[User.Role.OPERATIONS]
    approver = users[User.Role.APPROVER]
    finance = users[User.Role.FINANCE]
    advance = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=advance, actor=operations)
    decide_batch(batch=advance, actor=approver, decision=ApprovalAction.Action.APPROVE)
    advance_item = advance.items.get()
    create_paid_payment(
        actor=finance,
        vendor=trip.vendor,
        payment_date=timezone.localdate(),
        utr_reference="SETTLE-ADVANCE",
        allocations=[
            {
                "approval_item_id": advance_item.pk,
                "gross_amount_allocated": advance_item.gross_requested,
                "tds_allocated": advance_item.tds_this_request,
                "net_cash_allocated": advance_item.net_requested,
            }
        ],
    )
    trip.status = Trip.Status.DELIVERED
    trip.actual_delivery_at = timezone.now()
    trip.save(update_fields=["status", "actual_delivery_at", "updated_at"])
    _document(trip, operations, Document.Kind.POD, "pod.pdf")
    _document(trip, operations, Document.Kind.VENDOR_INVOICE, "invoice.pdf")

    settlement = save_settlement(actor=operations, trip=trip, final_freight="52000")
    submit_settlement(actor=operations, settlement=settlement)
    settlement.refresh_from_db()
    decide_batch(
        batch=settlement.settlement_approval,
        actor=approver,
        decision=ApprovalAction.Action.APPROVE,
    )
    final_item = settlement.settlement_approval.items.get()
    create_paid_payment(
        actor=finance,
        vendor=trip.vendor,
        payment_date=timezone.localdate(),
        utr_reference="SETTLE-FINAL",
        allocations=[
            {
                "approval_item_id": final_item.pk,
                "gross_amount_allocated": final_item.gross_requested,
                "tds_allocated": final_item.tds_this_request,
                "net_cash_allocated": final_item.net_requested,
            }
        ],
    )
    ClientBilling.objects.create(
        trip=trip,
        client=trip.client,
        billing_amount="60000",
        invoice_no="NPL-INV-1",
        invoice_date=timezone.localdate(),
        payment_status=ClientBilling.Status.INVOICED,
        created_by=operations,
    )
    finalize_settlement(actor=operations, settlement=settlement)
    trip.refresh_from_db()
    assert trip.status == Trip.Status.SETTLED
    assert trip.final_settlement.remaining_cash_payable == 0


@pytest.mark.django_db
def test_approval_and_payment_queue_email_and_whatsapp_notices(trip_factory, users):
    trip = trip_factory(1)
    trip.vendor.email = "vendor@example.test"
    trip.vendor.primary_phone = "919876543210"
    trip.vendor.save(update_fields=["email", "primary_phone", "updated_at"])
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    decide_batch(
        batch=batch,
        actor=users[User.Role.APPROVER],
        decision=ApprovalAction.Action.APPROVE,
    )

    approval_notices = IntegrationMessage.objects.filter(
        object_type="approval",
        object_id=str(batch.pk),
        event_key="APPROVAL_COMPLETED",
    )
    assert set(approval_notices.values_list("channel", flat=True)) == {"EMAIL", "WHATSAPP"}
    assert set(approval_notices.values_list("recipient", flat=True)) == {
        "vendor@example.test",
        "919876543210",
    }

    item = batch.items.get()
    payment = create_paid_payment(
        actor=users[User.Role.FINANCE],
        vendor=trip.vendor,
        payment_date=timezone.localdate(),
        utr_reference="DUAL-NOTICE-1",
        allocations=[
            {
                "approval_item_id": item.pk,
                "gross_amount_allocated": item.gross_requested,
                "tds_allocated": item.tds_this_request,
                "net_cash_allocated": item.net_requested,
            }
        ],
    )
    payment_notices = IntegrationMessage.objects.filter(
        object_type="payment",
        object_id=str(payment.pk),
        event_key="PAYMENT_COMPLETED",
    )
    assert set(payment_notices.values_list("channel", flat=True)) == {"EMAIL", "WHATSAPP"}
    assert set(payment_notices.values_list("recipient", flat=True)) == {
        "vendor@example.test",
        "919876543210",
    }


@pytest.mark.django_db
def test_approver_and_finance_receive_email_whatsapp_and_secure_links(
    monkeypatch, trip_factory, users
):
    monkeypatch.setenv("WEB_ORIGIN", "https://transport.example.test")
    approver = users[User.Role.APPROVER]
    approver.email = "approver@example.test"
    approver.whatsapp_phone = "919811111111"
    approver.save(update_fields=["email", "whatsapp_phone"])
    finance = users[User.Role.FINANCE]
    finance.email = "accounts@example.test"
    finance.whatsapp_phone = "919822222222"
    finance.save(update_fields=["email", "whatsapp_phone"])

    batch = create_approval_batch(
        actor=users[User.Role.OPERATIONS], trips=[trip_factory(1)]
    )
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    approval_notices = IntegrationMessage.objects.filter(
        user=approver,
        event_key="APPROVAL_REQUESTED",
        object_id=str(batch.pk),
    )
    assert set(approval_notices.values_list("channel", flat=True)) == {
        "IN_APP",
        "EMAIL",
        "WHATSAPP",
    }
    whatsapp_approval = approval_notices.get(channel="WHATSAPP")
    assert f"https://transport.example.test/approvals/{batch.pk}" in whatsapp_approval.body_summary

    decide_batch(
        batch=batch,
        actor=approver,
        decision=ApprovalAction.Action.APPROVE,
    )
    finance_notices = IntegrationMessage.objects.filter(
        user=finance,
        event_key="FINANCE_READY",
        object_id=str(batch.pk),
    )
    assert set(finance_notices.values_list("channel", flat=True)) == {
        "IN_APP",
        "EMAIL",
        "WHATSAPP",
    }
    whatsapp_finance = finance_notices.get(channel="WHATSAPP")
    assert f"https://transport.example.test/finance?approval={batch.pk}" in whatsapp_finance.body_summary
    finance_options = json.loads(decrypt_value(whatsapp_finance.payload_encrypted))["provider_options"]
    assert finance_options["template_name"] == "drona_logitech_finance_ready"
    assert finance_options["body_parameters"] == [
        batch.approval_no,
        "operations",
        "approver",
        "1",
        "47500.00",
        "450.00",
        "47050.00",
    ]
    assert finance_options["url_button_parameters"] == [str(batch.pk)]


@pytest.mark.django_db
def test_operations_receive_templated_approval_payment_and_settlement_updates(
    monkeypatch, trip_factory, users
):
    monkeypatch.setenv("WEB_ORIGIN", "https://transport.example.test")
    operations = users[User.Role.OPERATIONS]
    operations.email = "operations@example.test"
    operations.whatsapp_phone = "919833333333"
    operations.save(update_fields=["email", "whatsapp_phone"])
    trip = trip_factory(1)
    batch = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=batch, actor=operations)
    decide_batch(
        batch=batch,
        actor=users[User.Role.APPROVER],
        decision=ApprovalAction.Action.APPROVE,
    )

    approval_notices = IntegrationMessage.objects.filter(
        user=operations,
        event_key="APPROVAL_COMPLETED",
        object_id=str(batch.pk),
    )
    assert set(approval_notices.values_list("channel", flat=True)) == {
        "IN_APP",
        "EMAIL",
        "WHATSAPP",
    }
    approval_whatsapp = approval_notices.get(channel="WHATSAPP")
    approval_options = json.loads(decrypt_value(approval_whatsapp.payload_encrypted))["provider_options"]
    assert approval_options["template_name"] == "drona_logitech_operations_approval"
    assert approval_options["body_parameters"][1] == "Approved"
    assert approval_options["url_button_parameters"] == [str(batch.pk)]

    item = batch.items.get()
    payment = create_paid_payment(
        actor=users[User.Role.FINANCE],
        vendor=trip.vendor,
        payment_date=timezone.localdate(),
        utr_reference="OPS-NOTICE-1",
        allocations=[
            {
                "approval_item_id": item.pk,
                "gross_amount_allocated": item.gross_requested,
                "tds_allocated": item.tds_this_request,
                "net_cash_allocated": item.net_requested,
            }
        ],
    )
    payment_notices = IntegrationMessage.objects.filter(
        user=operations,
        event_key="PAYMENT_COMPLETED",
        object_id=str(payment.pk),
    )
    assert set(payment_notices.values_list("channel", flat=True)) == {
        "IN_APP",
        "EMAIL",
        "WHATSAPP",
    }
    payment_whatsapp = payment_notices.get(channel="WHATSAPP")
    payment_options = json.loads(decrypt_value(payment_whatsapp.payload_encrypted))["provider_options"]
    assert payment_options["template_name"] == "drona_logitech_operations_payment"
    assert payment_options["body_parameters"][:7] == [
        payment.payment_no,
        trip.vendor.display_name,
        "1",
        "47500.00",
        "450.00",
        "47050.00",
        "OPS-NOTICE-1",
    ]
    assert payment_options["url_button_parameters"] == [str(payment.pk)]

    trip.actual_delivery_at = timezone.now()
    trip.save(update_fields=["actual_delivery_at", "updated_at"])
    emit_event("SETTLEMENT_PENDING", instance=trip, actor=operations)
    settlement_whatsapp = IntegrationMessage.objects.get(
        user=operations,
        channel="WHATSAPP",
        event_key="SETTLEMENT_PENDING",
        object_id=str(trip.pk),
    )
    settlement_options = json.loads(decrypt_value(settlement_whatsapp.payload_encrypted))["provider_options"]
    assert settlement_options["template_name"] == "drona_logitech_operations_settlement"
    assert settlement_options["body_parameters"][:3] == [
        trip.trip_no,
        "Sonipat to Ghaziabad",
        trip.vendor.display_name,
    ]
    assert settlement_options["url_button_parameters"] == [str(trip.pk)]


@pytest.mark.django_db
def test_import_confirmation_creates_masters_and_trip(users):
    client = Client.objects.create(code="IMP", name="Import Client")
    row = {
        "row_no": 2,
        "valid": True,
        "errors": [],
        "warnings": [],
        "normalized": {
            "source_row_no": 1,
            "origin": "Sonipat",
            "destination": "Delhi",
            "deployment_date": str(timezone.localdate()),
            "expected_delivery_date": str(timezone.localdate() + timedelta(days=1)),
            "uom_ltrs": "LTRS",
            "quantity": "10",
            "total_load": "20000",
            "vendor_freight_rate": "50000.00",
            "unloading": "2500.00",
            "vendor": "Imported Vendor",
            "vehicle_registration": "HR10IMP01",
            "driver_name": "Imported Driver",
            "driver_phone": "0000000000",
            "vehicle_type": "32 FT",
        },
    }
    job = ImportJob.objects.create(
        uploaded_by=users[User.Role.OPERATIONS],
        original_filename="legacy.xlsx",
        row_count=1,
        valid_count=1,
        source_hash="c" * 64,
        summary={"rows": [row]},
    )
    confirm_import(
        job=job,
        actor=users[User.Role.OPERATIONS],
        client_id=client.pk,
        create_missing=True,
    )
    job.refresh_from_db()
    assert job.status == "COMPLETED"
    assert Trip.objects.filter(pk__in=job.result["created_trip_ids"]).count() == 1


@pytest.mark.django_db
def test_report_catalog_exports_csv_and_xlsx(trip_factory):
    trip_factory(1)
    assert len(REPORT_CATALOG) == 14
    report = build_report("trip-cost-payment", {})
    assert report.rows
    assert export_csv(report).startswith(b"\xef\xbb\xbf")
    assert export_xlsx(report, "Trips").startswith(b"PK")


@pytest.mark.django_db
def test_mfa_setup_confirmation_and_encrypted_outbox(users):
    user = users[User.Role.OPERATIONS]
    client = APIClient()
    client.force_authenticate(user)
    setup = client.post("/api/auth/mfa/setup/", {}, format="json")
    assert setup.status_code == 200
    otp = _code(setup.data["secret"], int(time.time()) // 30)
    confirmed = client.post("/api/auth/mfa/confirm/", {"otp": otp}, format="json")
    assert confirmed.status_code == 200
    user.refresh_from_db()
    assert user.mfa_enabled is True
    assert setup.data["secret"] not in user.mfa_secret_encrypted

    message = queue_message(
        channel="EMAIL",
        recipient="person@example.test",
        subject="Secret subject",
        body="Sensitive reset link",
        object_type="account",
        object_id=user.pk,
        idempotency_key="encrypted-outbox-test",
        user=user,
    )
    assert "Sensitive reset link" not in message.payload_encrypted


@pytest.mark.django_db
def test_internal_comment_never_notifies_transporter(trip_factory, users):
    trip = trip_factory(1)
    transporter = User.objects.create_user(
        username="mentioned-transporter",
        password="StrongPass123!",
        role=User.Role.TRANSPORTER,
        vendor=trip.vendor,
    )
    client = APIClient()
    client.force_authenticate(users[User.Role.OPERATIONS])
    response = client.post(
        "/api/comments/",
        {
            "object_type": "trip",
            "object_id": str(trip.pk),
            "body": "Internal-only note",
            "visibility": "INTERNAL",
            "mentions": [transporter.pk],
        },
        format="json",
    )
    assert response.status_code == 201
    assert not IntegrationMessage.objects.filter(user=transporter).exists()
