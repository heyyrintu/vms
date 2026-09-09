import json

import pytest
from django.core.files.base import ContentFile

from accounts.models import User
from approvals.models import ApprovalAction
from approvals.services import create_approval_batch, decide_batch, submit_batch
from core.crypto import decrypt_value
from integrations.email_builder import build_document
from integrations.models import IntegrationMessage
from integrations.services import deliver_message
from operations.models import Document, Vendor, VendorBankAccount
from payments.finance_brief import (
    attachment_plan,
    build_payout_brief,
    payout_summary,
    vendor_payouts,
)


def _document(*, object_type, object_id, kind, uploaded_by, name="scan.pdf", size=None):
    content = b"%PDF-1.4\n" + name.encode()
    return Document.objects.create(
        object_type=object_type,
        object_id=str(object_id),
        kind=kind,
        file=ContentFile(content, name=name),
        original_name=name,
        content_type="application/pdf",
        # `size` is the row the attachment budget is weighed against, so a test can
        # declare an oversized document without writing megabytes to disk.
        size=len(content) if size is None else size,
        uploaded_by=uploaded_by,
        scan_status="CLEAN",
    )


@pytest.fixture
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def approved_batch(db, media_root, trip_factory, users):
    vendor = Vendor.objects.create(
        vendor_code="V-900",
        legal_name="Sharma Roadways Pvt Ltd",
        display_name="Sharma Roadways",
        tax_identifier="ABCDE1234F",
        payment_terms="Net 7",
    )
    trip = trip_factory(9, vendor=vendor)
    account = VendorBankAccount.objects.create(
        vendor=vendor,
        bank_name="HDFC Bank",
        account_holder="Sharma Roadways Pvt Ltd",
        account_number_encrypted="encrypted",
        account_last_four="4821",
        ifsc_code="HDFC0001234",
    )
    operations = users[User.Role.OPERATIONS]
    finance = users[User.Role.FINANCE]
    finance.email = "accounts@example.test"
    finance.save(update_fields=["email"])
    _document(object_type="vendor", object_id=vendor.pk, kind=Document.Kind.PAN, uploaded_by=operations)
    _document(
        object_type="vendor_bank_account",
        object_id=account.pk,
        kind=Document.Kind.CANCELLED_CHEQUE,
        uploaded_by=operations,
    )
    _document(object_type="trip", object_id=trip.pk, kind=Document.Kind.LR, uploaded_by=operations)
    batch = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=batch, actor=operations)
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)
    return batch


def test_brief_carries_the_payee_bank_and_evidence(approved_batch):
    brief = build_payout_brief(vendor_payouts(approved_batch))

    assert "Sharma Roadways:" in brief
    assert "Vendor code: V-900" in brief
    assert "PAN / GSTIN: ABCDE1234F" in brief
    assert "Payment terms: Net 7" in brief
    assert "Bank: HDFC Bank" in brief
    assert "Account holder: Sharma Roadways Pvt Ltd" in brief
    assert "IFSC: HDFC0001234" in brief
    assert "Cancelled cheque: On file" in brief
    assert "Vendor KYC: PAN" in brief
    assert "Net to transfer: 47,050.00" in brief
    assert "Docs: LR" in brief
    # POD and the vendor invoice are still missing, and finance must know that.
    assert "Missing trip evidence: POD, Vendor invoice." in brief


def test_brief_never_exposes_a_full_account_number(approved_batch):
    brief = build_payout_brief(vendor_payouts(approved_batch))

    assert "•••• 4821" in brief
    assert "encrypted" not in brief


def test_brief_flags_a_vendor_without_a_verified_account(db, trip_factory, users):
    vendor = Vendor.objects.create(
        vendor_code="V-901", legal_name="No Bank Ltd", display_name="No Bank"
    )
    trip = trip_factory(11, vendor=vendor)
    operations = users[User.Role.OPERATIONS]
    batch = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=batch, actor=operations)
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)

    brief = build_payout_brief(vendor_payouts(batch))

    assert "No active bank account is on file for No Bank." in brief
    assert payout_summary(vendor_payouts(batch)) == "1 vendor, 1 trip, net 47,050.00"


def test_finance_email_carries_the_brief_but_the_short_channels_do_not(approved_batch):
    notices = IntegrationMessage.objects.filter(
        event_key="FINANCE_READY", object_id=str(approved_batch.pk)
    )
    email = notices.filter(channel="EMAIL").first()
    in_app = notices.filter(channel="IN_APP").first()

    email_body = json.loads(decrypt_value(email.payload_encrypted))["body"]
    assert "Bank: HDFC Bank" in email_body
    assert "•••• 4821" in email_body
    assert f"/finance?approval={approved_batch.pk}" in email_body
    # The feed and the message log stay one line long.
    assert "Bank: HDFC Bank" not in in_app.body_summary
    assert "1 vendor, 1 trip" in email.body_summary
    assert "Bank: HDFC Bank" not in email.body_summary


def test_email_layout_turns_each_payout_into_its_own_section(approved_batch):
    email = IntegrationMessage.objects.get(
        event_key="FINANCE_READY", object_id=str(approved_batch.pk), channel="EMAIL"
    )
    body = json.loads(decrypt_value(email.payload_encrypted))["body"]

    document = build_document(
        subject="Payment ready",
        body=body,
        event_key="FINANCE_READY",
        object_type="approvals.paymentapprovalbatch",
    )
    kinds = [kind for kind, _value in document["blocks"]]
    facts = [row for kind, value in document["blocks"] if kind == "facts" for row in value]
    items = [row for kind, value in document["blocks"] if kind == "items" for row in value]

    assert "section" in kinds
    assert ("Bank", "HDFC Bank") in facts
    assert ("Account number", "•••• 4821") in facts
    assert items[0]["metrics"] == [
        ("Gross", "47,500.00"),
        ("TDS", "450.00"),
        ("Net", "47,050.00"),
    ]
    assert "Docs: LR" in items[0]["subtitle"]


def _email_notice(batch):
    return IntegrationMessage.objects.get(
        event_key="FINANCE_READY", object_id=str(batch.pk), channel="EMAIL"
    )


def _payload(message):
    return json.loads(decrypt_value(message.payload_encrypted))


def test_finance_email_attaches_every_clean_document_behind_the_payout(approved_batch):
    payload = _payload(_email_notice(approved_batch))
    specs = payload["provider_options"]["attachment_documents"]

    assert {spec["id"] for spec in specs} == set(
        Document.objects.values_list("pk", flat=True)
    )
    # Payment-critical evidence first, so a tight budget keeps the cheque.
    assert [spec["filename"].split("-")[-2] for spec in specs] == [
        "CANCELLED_CHEQUE",
        "LR",
        "PAN",
    ]
    assert "Attached: 3 files" in payload["body"]
    assert "Attached documents: Cancelled cheque, LR, PAN" in payload["body"]
    # The short channels stay short.
    in_app = IntegrationMessage.objects.get(
        event_key="FINANCE_READY", object_id=str(approved_batch.pk), channel="IN_APP"
    )
    assert "Attached" not in in_app.body_summary
    whatsapp = IntegrationMessage.objects.filter(
        event_key="FINANCE_READY", object_id=str(approved_batch.pk), channel="WHATSAPP"
    ).first()
    assert whatsapp is None or "attachment_documents" not in _payload(whatsapp)["provider_options"]


def test_attachment_filenames_are_scoped_to_the_vendor_and_trip(approved_batch):
    trip = approved_batch.items.first().trip
    filenames = {
        spec["filename"]
        for spec in _payload(_email_notice(approved_batch))["provider_options"][
            "attachment_documents"
        ]
    }

    # Two vendors can both have uploaded `scan.pdf`; the owner disambiguates them.
    assert "V-900-PAN-scan.pdf" in filenames
    assert "V-900-CANCELLED_CHEQUE-scan.pdf" in filenames
    assert f"{trip.trip_no}-LR-scan.pdf" in filenames


def test_an_oversized_document_is_skipped_and_named_in_the_body(approved_batch, users):
    trip = approved_batch.items.first().trip
    _document(
        object_type="trip",
        object_id=trip.pk,
        kind=Document.Kind.POD,
        uploaded_by=users[User.Role.OPERATIONS],
        name="huge-pod.pdf",
        size=20 * 1024 * 1024,
    )
    groups = vendor_payouts(approved_batch)

    specs, skipped = attachment_plan(groups)
    body = build_payout_brief(groups, attachments=specs, skipped=skipped)

    assert "huge-pod.pdf" not in {spec["filename"] for spec in specs}
    assert len(specs) == 3
    assert skipped == [f"POD ({trip.trip_no})"]
    assert (
        f"One document exceeds the email attachment limit and can be opened from the "
        f"finance queue: POD ({trip.trip_no})." in body
    )


def test_the_budget_is_configurable(approved_batch, monkeypatch):
    monkeypatch.setenv("FINANCE_EMAIL_ATTACHMENT_LIMIT_MB", "0")

    specs, skipped = attachment_plan(vendor_payouts(approved_batch))

    assert specs == []
    assert len(skipped) == 3


def test_delivery_survives_a_document_deleted_after_queueing(
    db, media_root, monkeypatch, trip_factory, users
):
    monkeypatch.setenv("EMAIL_PROVIDER", "fake")
    vendor = Vendor.objects.create(
        vendor_code="V-902", legal_name="Late Delete Ltd", display_name="Late Delete"
    )
    trip = trip_factory(13, vendor=vendor)
    operations = users[User.Role.OPERATIONS]
    finance = users[User.Role.FINANCE]
    finance.email = "accounts@example.test"
    finance.save(update_fields=["email"])
    _document(
        object_type="vendor", object_id=vendor.pk, kind=Document.Kind.PAN, uploaded_by=operations
    )
    doomed = _document(
        object_type="trip", object_id=trip.pk, kind=Document.Kind.LR, uploaded_by=operations
    )
    batch = create_approval_batch(actor=operations, trips=[trip])
    submit_batch(batch=batch, actor=operations)
    decide_batch(
        batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE
    )
    message = _email_notice(batch)
    assert len(_payload(message)["provider_options"]["attachment_documents"]) == 2

    doomed.delete()
    delivered = deliver_message(message)

    assert delivered.status == "SENT"
    assert delivered.raw_metadata["attachment_count"] == 1
