import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO

from django.db.models import Sum
from django.utils import timezone
from openpyxl import Workbook

from approvals.calculations import calculate_profitability
from approvals.models import PaymentApprovalItem
from operations.models import Trip, Vendor

from .models import ClientBilling, FinancePaymentTransaction, PaymentAllocation, TDSEntry
from .services import paid_totals


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
    return queryset


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
                "billing": billing.billing_amount,
                "vendor_cost": vendor_cost,
                "internal_costs": billing.internal_trip_costs,
                "gross_profit": profit["gross_profit"],
                "margin_percent": profit["margin_percent"],
            }
        )
    return _with_money_totals(rows, ["billing", "vendor_cost", "internal_costs", "gross_profit"])


def _trip_financial_row(trip):
    items = trip.approval_items.filter(item_status=PaymentApprovalItem.Status.APPROVED)
    approved = items.aggregate(total=Sum("gross_requested"))["total"] or Decimal("0")
    allocations = trip.payment_allocations.filter(payment__status=FinancePaymentTransaction.Status.PAID)
    cash = allocations.aggregate(total=Sum("net_cash_allocated"))["total"] or Decimal("0")
    tds = allocations.aggregate(total=Sum("tds_allocated"))["total"] or Decimal("0")
    settlement = getattr(trip, "final_settlement", None)
    return {
        "trip": trip.trip_no,
        "date": trip.deployment_date,
        "vendor": trip.vendor.display_name,
        "status": trip.status,
        "vendor_cost": settlement.total_vendor_gross_cost if settlement else trip.vendor_freight_rate,
        "approved_gross": approved,
        "cash_paid": cash,
        "tds": tds,
        "remaining": approved - cash - tds,
    }


def _vendor_report(slug, trips):
    rows = []
    today = timezone.localdate()
    for vendor in Vendor.objects.filter(trips__in=trips).distinct().order_by("display_name"):
        vendor_trips = trips.filter(vendor=vendor)
        business = vendor_trips.aggregate(total=Sum("vendor_freight_rate"))["total"] or Decimal("0")
        allocations = PaymentAllocation.objects.filter(
            payment__vendor=vendor,
            payment__status=FinancePaymentTransaction.Status.PAID,
            trip__in=vendor_trips,
        )
        cash = allocations.aggregate(total=Sum("net_cash_allocated"))["total"] or Decimal("0")
        tds = allocations.aggregate(total=Sum("tds_allocated"))["total"] or Decimal("0")
        unresolved = sum(
            (_trip_financial_row(trip)["remaining"] for trip in vendor_trips), Decimal("0")
        )
        oldest = (
            PaymentApprovalItem.objects.filter(
                vendor=vendor, trip__in=vendor_trips, item_status=PaymentApprovalItem.Status.APPROVED
            )
            .order_by("batch__submitted_at")
            .values_list("batch__submitted_at", flat=True)
            .first()
        )
        row = {
            "vendor": vendor.display_name,
            "trips": vendor_trips.count(),
            "business": business,
            "cash_paid": cash,
            "tds": tds,
            "unresolved": unresolved,
            "oldest_unresolved_days": (today - oldest.date()).days if oldest else 0,
        }
        if slug == "vendor-advance-outstanding":
            row["advance_cash_paid_unsettled"] = (
                vendor_trips.exclude(settlement_status="SETTLED")
                .filter(payment_allocations__payment__status="PAID")
                .aggregate(total=Sum("payment_allocations__net_cash_allocated"))["total"]
                or Decimal("0")
            )
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
