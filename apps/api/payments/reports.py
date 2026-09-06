import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO

from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from openpyxl import Workbook

from approvals.calculations import calculate_profitability
from approvals.models import PaymentApprovalItem
from operations.models import Trip

from .models import ClientBilling, FinancePaymentTransaction, PaymentAllocation, TDSEntry
from .services import paid_totals

MONEY = DecimalField(max_digits=14, decimal_places=2)


@dataclass
class ReportData:
    columns: list[str]
    rows: list[dict]
    totals: dict


REPORT_CATALOG = {
    "pending-approvals": "Pending approvals",
    "approved-unpaid": "Approved but unpaid",
    "payments": "Paid transactions",
    "vendor-advance-outstanding": "Vendor advance outstanding",
    "vendor-business": "Vendor-wise business",
    "vendor-payments": "Vendor-wise payments",
    "tds": "TDS register",
    "trip-cost-payment": "Trip-wise cost and payment",
    "unsettled": "Completed but unsettled",
    "cancelled-with-advance": "Cancelled trips with an advance",
    "pod-pending": "POD pending",
    "billing-pending": "Client billing pending",
    "profitability": "Trip profitability",
    "vendor-aging": "Vendor aging and unresolved balances",
}


def _filtered_trips(params):
    queryset = Trip.objects.select_related("vendor", "client", "indent")
    if params.get("date_from"):
        queryset = queryset.filter(deployment_date__gte=params["date_from"])
    if params.get("date_to"):
        queryset = queryset.filter(deployment_date__lte=params["date_to"])
    for field in ("vendor", "client"):
        if params.get(field):
            queryset = queryset.filter(**{f"{field}_id": params[field]})
    if params.get("branch"):
        queryset = queryset.filter(branch__iexact=params["branch"])
    return annotate_financials(queryset)


def _money_subquery(queryset, group_field, sum_field):
    """Sum ``sum_field`` for the rows of ``queryset`` that belong to the outer row."""
    totals = queryset.order_by().values(group_field).annotate(total=Sum(sum_field)).values("total")[:1]
    return Coalesce(Subquery(totals, output_field=MONEY), Value(Decimal("0")), output_field=MONEY)


def annotate_financials(trips):
    """Attach approved, cash-paid and TDS totals so report rows need no per-trip queries."""
    approved = PaymentApprovalItem.objects.filter(
        trip=OuterRef("pk"), item_status=PaymentApprovalItem.Status.APPROVED
    )
    paid = PaymentAllocation.objects.filter(
        trip=OuterRef("pk"), payment__status=FinancePaymentTransaction.Status.PAID
    )
    return trips.select_related("final_settlement").annotate(
        approved_gross_total=_money_subquery(approved, "trip", "gross_requested"),
        cash_paid_total=_money_subquery(paid, "trip", "net_cash_allocated"),
        tds_paid_total=_money_subquery(paid, "trip", "tds_allocated"),
    )


def build_report(slug, params):
    if slug not in REPORT_CATALOG:
        raise ValueError("Unknown report")
    trips = _filtered_trips(params)
    if slug == "pending-approvals":
        items = PaymentApprovalItem.objects.filter(
            trip__in=trips, item_status=PaymentApprovalItem.Status.PENDING
        ).select_related("batch", "trip", "vendor")
        rows = [
            {
                "approval": item.batch.approval_no,
                "trip": item.trip.trip_no,
                "vendor": item.vendor.display_name,
                "submitted": item.batch.submitted_at,
                "gross": item.gross_requested,
                "tds": item.tds_this_request,
                "net": item.net_requested,
                "stage": item.batch.current_stage,
            }
            for item in items
        ]
        return _with_money_totals(rows, ["gross", "tds", "net"])
    if slug == "approved-unpaid":
        rows = []
        items = PaymentApprovalItem.objects.filter(
            trip__in=trips, item_status=PaymentApprovalItem.Status.APPROVED
        ).select_related("batch", "trip", "vendor")
        for item in items:
            paid = paid_totals(item)
            if item.net_requested - paid["net"] > 0:
                rows.append(
                    {
                        "approval": item.batch.approval_no,
                        "trip": item.trip.trip_no,
                        "vendor": item.vendor.display_name,
                        "gross_remaining": item.gross_requested - paid["gross"],
                        "tds_remaining": item.tds_this_request - paid["tds"],
                        "net_remaining": item.net_requested - paid["net"],
                    }
                )
        return _with_money_totals(rows, ["gross_remaining", "tds_remaining", "net_remaining"])
    if slug == "payments":
        payments = FinancePaymentTransaction.objects.filter(
            allocations__trip__in=trips, status=FinancePaymentTransaction.Status.PAID
        ).select_related("vendor").distinct()
        if params.get("date_from"):
            payments = payments.filter(payment_date__gte=params["date_from"])
        if params.get("date_to"):
            payments = payments.filter(payment_date__lte=params["date_to"])
        rows = [
            {
                "payment": payment.payment_no,
                "date": payment.payment_date,
                "vendor": payment.vendor.display_name,
                "utr": payment.utr_reference,
                "gross": payment.gross_allocated_amount,
                "tds": payment.tds_amount,
                "net": payment.net_paid_amount,
            }
            for payment in payments
        ]
        return _with_money_totals(rows, ["gross", "tds", "net"])
    if slug in {"vendor-business", "vendor-payments", "vendor-advance-outstanding", "vendor-aging"}:
        return _vendor_report(slug, trips)
    if slug == "tds":
        entries = TDSEntry.objects.filter(trip__in=trips).select_related("vendor", "trip", "payment")
        rows = [
            {
                "date": entry.deduction_date,
                "vendor": entry.vendor.display_name,
                "trip": entry.trip.trip_no,
                "payment": entry.payment.payment_no,
                "taxable_base": entry.taxable_base,
                "rate": entry.rate,
                "tds": entry.tds_amount,
                "status": entry.status,
            }
            for entry in entries
        ]
        return _with_money_totals(rows, ["taxable_base", "tds"])
    if slug == "trip-cost-payment":
        rows = [_trip_financial_row(trip) for trip in trips]
        return _with_money_totals(rows, ["vendor_cost", "approved_gross", "cash_paid", "tds", "remaining"])
    if slug == "unsettled":
        rows = [
            _trip_financial_row(trip)
            for trip in trips.filter(status__in=[Trip.Status.DELIVERED, Trip.Status.SETTLEMENT_PENDING, Trip.Status.SETTLEMENT_APPROVAL_PENDING])
        ]
        return _with_money_totals(rows, ["vendor_cost", "approved_gross", "cash_paid", "tds", "remaining"])
    if slug == "cancelled-with-advance":
        rows = [
            _trip_financial_row(trip)
            for trip in trips.filter(status=Trip.Status.CANCELLED_WITH_PAYMENT)
        ]
        return _with_money_totals(rows, ["vendor_cost", "approved_gross", "cash_paid", "tds", "remaining"])
    if slug == "pod-pending":
        rows = [
            {
                "trip": trip.trip_no,
                "date": trip.deployment_date,
                "vendor": trip.vendor.display_name,
                "route": f"{trip.origin} → {trip.destination}",
                "status": trip.status,
                "pod_status": trip.pod_status,
            }
            for trip in trips.filter(pod_status="PENDING")
        ]
        return ReportData(list(rows[0]) if rows else ["trip", "date", "vendor", "route", "status", "pod_status"], rows, {})
    if slug == "billing-pending":
        rows = []
        for trip in trips.filter(status__in=[Trip.Status.DELIVERED, Trip.Status.SETTLEMENT_PENDING, Trip.Status.SETTLEMENT_APPROVAL_PENDING, Trip.Status.SETTLED]):
            billing = getattr(trip, "billing", None)
            if not billing or billing.payment_status != ClientBilling.Status.RECEIVED:
                rows.append(
                    {
                        "trip": trip.trip_no,
                        "client": trip.client.name,
                        "billing_amount": billing.billing_amount if billing else Decimal("0"),
                        "invoice": billing.invoice_no if billing else "",
                        "status": billing.payment_status if billing else "NOT_CREATED",
                    }
                )
        return _with_money_totals(rows, ["billing_amount"])
    rows = []
    for trip in trips:
        billing = getattr(trip, "billing", None)
        settlement = getattr(trip, "final_settlement", None)
        if not billing:
            continue
        vendor_cost = settlement.total_vendor_gross_cost if settlement else trip.vendor_freight_rate
        profit = calculate_profitability(
            client_billing_amount=billing.billing_amount,
            final_vendor_gross_cost=vendor_cost,
            internal_costs=billing.internal_trip_costs,
        )
        rows.append(
            {
                "trip": trip.trip_no,
                "client": trip.client.name,
                "vendor": trip.vendor.display_name,
                "basis": "SETTLED" if settlement else "PROVISIONAL",
                "billing": billing.billing_amount,
                "vendor_cost": vendor_cost,
                "internal_costs": billing.internal_trip_costs,
                "gross_profit": profit["gross_profit"],
                "margin_percent": profit["margin_percent"],
            }
        )
    return _with_money_totals(rows, ["billing", "vendor_cost", "internal_costs", "gross_profit"])


def _trip_financial_row(trip):
    """Build a row from a trip produced by ``annotate_financials``."""
    settlement = getattr(trip, "final_settlement", None)
    return {
        "trip": trip.trip_no,
        "date": trip.deployment_date,
        "vendor": trip.vendor.display_name,
        "status": trip.status,
        "vendor_cost": settlement.total_vendor_gross_cost if settlement else trip.vendor_freight_rate,
        "approved_gross": trip.approved_gross_total,
        "cash_paid": trip.cash_paid_total,
        "tds": trip.tds_paid_total,
        "remaining": trip.approved_gross_total - trip.cash_paid_total - trip.tds_paid_total,
    }


def _vendor_report(slug, trips):
    today = timezone.localdate()
    groups = {}
    for trip in trips.order_by("vendor__display_name", "pk"):
        group = groups.setdefault(
            trip.vendor_id,
            {
                "vendor": trip.vendor.display_name,
                "trips": 0,
                "business": Decimal("0"),
                "cash_paid": Decimal("0"),
                "tds": Decimal("0"),
                "unresolved": Decimal("0"),
                "advance_cash_paid_unsettled": Decimal("0"),
                "trip_ids": [],
            },
        )
        group["trips"] += 1
        group["business"] += trip.vendor_freight_rate
        group["cash_paid"] += trip.cash_paid_total
        group["tds"] += trip.tds_paid_total
        group["unresolved"] += trip.approved_gross_total - trip.cash_paid_total - trip.tds_paid_total
        if trip.settlement_status != "SETTLED":
            group["advance_cash_paid_unsettled"] += trip.cash_paid_total
        group["trip_ids"].append(trip.pk)
    paid_per_item = PaymentAllocation.objects.filter(
        approval_item=OuterRef("pk"), payment__status=FinancePaymentTransaction.Status.PAID
    )
    rows = []
    for vendor_id, group in groups.items():
        oldest = (
            PaymentApprovalItem.objects.filter(
                vendor_id=vendor_id,
                trip_id__in=group["trip_ids"],
                item_status=PaymentApprovalItem.Status.APPROVED,
            )
            .annotate(paid_gross_total=_money_subquery(paid_per_item, "approval_item", "gross_amount_allocated"))
            .filter(gross_requested__gt=F("paid_gross_total"))
            .order_by("batch__submitted_at")
            .values_list("batch__submitted_at", flat=True)
            .first()
        )
        row = {key: value for key, value in group.items() if key not in {"trip_ids", "advance_cash_paid_unsettled"}}
        row["oldest_unresolved_days"] = (today - oldest.date()).days if oldest else 0
        if slug == "vendor-advance-outstanding":
            row["advance_cash_paid_unsettled"] = group["advance_cash_paid_unsettled"]
        rows.append(row)
    money_fields = ["business", "cash_paid", "tds", "unresolved"]
    if slug == "vendor-advance-outstanding":
        money_fields.append("advance_cash_paid_unsettled")
    return _with_money_totals(rows, money_fields)


def _with_money_totals(rows, money_fields):
    columns = list(rows[0]) if rows else money_fields
    totals = {field: sum((Decimal(str(row.get(field, 0) or 0)) for row in rows), Decimal("0")) for field in money_fields}
    return ReportData(columns, rows, totals)


def export_csv(report):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=report.columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(report.rows)
    return output.getvalue().encode("utf-8-sig")


def export_xlsx(report, title):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.append(report.columns)
    for row in report.rows:
        sheet.append([_excel_value(row.get(column)) for column in report.columns])
    if report.totals:
        sheet.append([])
        sheet.append(["TOTALS", *[report.totals.get(column, "") for column in report.columns[1:]]])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _excel_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value
    return str(value) if value is not None else ""
