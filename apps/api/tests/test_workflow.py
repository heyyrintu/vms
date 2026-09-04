from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from approvals.models import ApprovalAction, PaymentApprovalBatch, PaymentApprovalItem
from approvals.services import create_approval_batch, decide_batch, submit_batch
from audit.models import AuditLog
from payments.models import FinancePaymentTransaction
from payments.services import create_paid_payment, paid_totals, reverse_payment


@pytest.mark.django_db
def test_end_to_end_multi_vendor_approval_payment_and_reversal(trip_factory, users):
    trip_a = trip_factory(1)
    trip_b = trip_factory(2)
    operations = users[User.Role.OPERATIONS]
    approver = users[User.Role.APPROVER]
    finance = users[User.Role.FINANCE]

    batch = create_approval_batch(actor=operations, trips=[trip_a, trip_b])
    assert batch.items.values("vendor_id").distinct().count() == 2
    submit_batch(batch=batch, actor=operations)
    decide_batch(batch=batch, actor=approver, decision=ApprovalAction.Action.APPROVE)
    batch.refresh_from_db()
    assert batch.status == PaymentApprovalBatch.Status.APPROVED

    item_a, item_b = list(batch.items.order_by("id"))
    with pytest.raises(ValueError, match="payment vendor"):
        create_paid_payment(
            actor=finance,
            vendor=item_a.vendor,
            payment_date=timezone.localdate(),
            utr_reference="UTR-MIXED",
            allocations=[
                {"approval_item_id": item_b.pk, "gross_amount_allocated": item_b.gross_requested, "tds_allocated": item_b.tds_this_request, "net_cash_allocated": item_b.net_requested}
            ],
        )

    payment = create_paid_payment(
        actor=finance,
        vendor=item_a.vendor,
        payment_date=timezone.localdate(),
        utr_reference="UTR-1001",
        allocations=[
            {"approval_item_id": item_a.pk, "gross_amount_allocated": item_a.gross_requested, "tds_allocated": item_a.tds_this_request, "net_cash_allocated": item_a.net_requested}
        ],
    )
    assert payment.status == FinancePaymentTransaction.Status.PAID
    assert paid_totals(item_a)["net"] == item_a.net_requested
    assert payment.tds_entries.get().trip_id == trip_a.pk
    with pytest.raises(ValidationError, match="immutable"):
        payment.net_paid_amount -= Decimal("1")
        payment.save()
    payment.refresh_from_db()
    reverse_payment(actor=finance, payment=payment, reason="Bank returned the transfer")
    assert paid_totals(item_a)["net"] == 0
    assert AuditLog.objects.filter(action="PAYMENT_REVERSED", object_id=str(payment.pk)).exists()


@pytest.mark.django_db
def test_partial_payment_and_overpayment_blocking(trip_factory, users):
    trip = trip_factory(1)
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE)
    item = batch.items.get()
    create_paid_payment(
        actor=users[User.Role.FINANCE],
        vendor=item.vendor,
        payment_date=timezone.localdate(),
        utr_reference="UTR-PART-1",
        allocations=[{"approval_item_id": item.pk, "gross_amount_allocated": "10000", "tds_allocated": "100", "net_cash_allocated": "9900"}],
    )
    assert paid_totals(item)["gross"] == Decimal("10000")
    with pytest.raises(ValueError, match="exceeds remaining"):
        create_paid_payment(
            actor=users[User.Role.FINANCE],
            vendor=item.vendor,
            payment_date=timezone.localdate(),
            utr_reference="UTR-OVER",
            allocations=[{"approval_item_id": item.pk, "gross_amount_allocated": item.gross_requested, "tds_allocated": item.tds_this_request, "net_cash_allocated": item.net_requested}],
        )


@pytest.mark.django_db
def test_partial_approval_and_required_reject_reason(trip_factory, users):
    trips = [trip_factory(1), trip_factory(2)]
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=trips)
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    first = batch.items.order_by("id").first()
    decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.APPROVE, item_ids=[first.pk])
    batch.refresh_from_db()
    assert batch.status == PaymentApprovalBatch.Status.PARTIALLY_APPROVED
    with pytest.raises(ValueError, match="reason"):
        decide_batch(batch=batch, actor=users[User.Role.APPROVER], decision=ApprovalAction.Action.REJECT)


@pytest.mark.django_db
def test_self_approval_is_blocked(trip_factory, users):
    requester = users[User.Role.APPROVER]
    batch = create_approval_batch(actor=requester, trips=[trip_factory(1)])
    batch.status = PaymentApprovalBatch.Status.PENDING
    batch.items.update(item_status=PaymentApprovalItem.Status.PENDING)
    batch.save()
    with pytest.raises(PermissionError, match="Self-approval"):
        decide_batch(batch=batch, actor=requester, decision=ApprovalAction.Action.APPROVE)

