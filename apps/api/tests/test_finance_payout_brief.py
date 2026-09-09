import json

import pytest

from accounts.models import User
from approvals.models import ApprovalAction
from approvals.services import create_approval_batch, decide_batch, submit_batch
from core.crypto import decrypt_value
from integrations.email_builder import build_document
from integrations.models import IntegrationMessage
from operations.models import Document, Vendor, VendorBankAccount
from payments.finance_brief import build_payout_brief, payout_summary, vendor_payouts


def _document(*, object_type, object_id, kind, uploaded_by, name="scan.pdf"):
    return Document.objects.create(
        object_type=object_type,
        object_id=str(object_id),
        kind=kind,
        file=name,
        original_name=name,
        content_type="application/pdf",
        size=1024,
        uploaded_by=uploaded_by,
        scan_status="CLEAN",
    )


@pytest.fixture
def approved_batch(db, trip_factory, users):
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
