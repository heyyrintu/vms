from decimal import Decimal

import pytest

from accounts.models import User
from payments.models import ClientBilling
from payments.reports import build_report
from tests.test_lifecycle_regressions import approval, payment


@pytest.mark.django_db
def test_trip_cost_report_uses_one_query_per_request_not_per_trip(trip_factory, users, django_assert_max_num_queries):
    for index in range(1, 6):
        batch = approval(trip_factory(index), users)
        payment(batch.items.get(), users, reference=f"UTR-{index}")
    with django_assert_max_num_queries(6):
        report = build_report("trip-cost-payment", {})
    assert len(report.rows) == 5
    row = report.rows[0]
    assert row["cash_paid"] > 0
    assert row["remaining"] == Decimal("0.00")


@pytest.mark.django_db
def test_vendor_aging_counts_only_unpaid_items(trip_factory, users):
    paid_batch = approval(trip_factory(1), users)
    payment(paid_batch.items.get(), users, reference="UTR-PAID")
    approval(trip_factory(2), users)  # approved, never paid
    report = build_report("vendor-aging", {})
    by_vendor = {row["vendor"]: row for row in report.rows}
    paid_vendor = paid_batch.items.get().vendor.display_name
    assert by_vendor[paid_vendor]["unresolved"] == Decimal("0")
    assert by_vendor[paid_vendor]["oldest_unresolved_days"] == 0
    unpaid_rows = [row for name, row in by_vendor.items() if name != paid_vendor]
    assert unpaid_rows and unpaid_rows[0]["unresolved"] > 0


@pytest.mark.django_db
def test_profitability_marks_unsettled_trips_as_provisional(trip_factory, users):
    trip = trip_factory(1)
    ClientBilling.objects.create(
        trip=trip,
        client=trip.client,
        billing_amount=Decimal("60000"),
        invoice_no="INV-1",
        payment_status=ClientBilling.Status.INVOICED,
        created_by=users[User.Role.OPERATIONS],
    )
    report = build_report("profitability", {})
    assert report.rows[0]["basis"] == "PROVISIONAL"
    assert "basis" in report.columns
