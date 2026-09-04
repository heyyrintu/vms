from decimal import Decimal

from django.db.models import Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import RolePermission, has_capability
from approvals.calculations import money
from approvals.models import PaymentApprovalItem
from operations.models import Document, Trip, Vendor, VendorBankAccount

from .models import (
    ClientBilling,
    FinalTripSettlement,
    FinancePaymentTransaction,
    PaymentAllocation,
    TDSEntry,
)
from .reports import REPORT_CATALOG, build_report, export_csv, export_xlsx
from .serializers import (
    ClientBillingSerializer,
    FinalTripSettlementSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    TDSEntrySerializer,
)
from .services import (
    create_paid_payment,
    finalize_settlement,
    paid_totals,
    reverse_payment,
    save_settlement,
    submit_settlement,
)


def _document_payload(document, request):
    return {
        "id": document.pk,
        "kind": document.kind,
        "original_name": document.original_name,
        "scan_status": document.scan_status,
        "uploaded_at": document.created_at,
        "download_url": request.build_absolute_uri(f"/api/documents/{document.pk}/download/"),
    }


def _financial_position(trip_queryset):
    """Return a consistent, cash-based vendor liability position for a trip set."""
    trips = list(trip_queryset)
    trip_ids = [trip.pk for trip in trips]
    zero = Decimal("0.00")
    if not trip_ids:
        return {
            "total_freight_100": zero,
            "total_advance_amount": zero,
            "freight_balance_after_advance": zero,
            "total_vendor_liability": zero,
            "cash_paid": zero,
            "tds_deducted": zero,
            "remaining_to_pay": zero,
        }

    paid_by_trip = {
        row["trip_id"]: row
        for row in PaymentAllocation.objects.filter(
            trip_id__in=trip_ids,
            payment__status=FinancePaymentTransaction.Status.PAID,
        )
        .values("trip_id")
        .annotate(cash=Sum("net_cash_allocated"), tds=Sum("tds_allocated"))
    }
    settlements = {
        settlement.trip_id: settlement
        for settlement in FinalTripSettlement.objects.filter(trip_id__in=trip_ids)
    }

    total_freight = zero
    total_advance = zero
    total_liability = zero
    total_cash = zero
    total_tds = zero
    total_remaining = zero
    for trip in trips:
        freight = money(trip.vendor_freight_rate)
        advance = money(freight * trip.advance_percent / Decimal("100"))
        paid = paid_by_trip.get(trip.pk, {})
        cash = money(paid.get("cash") or zero)
        tds = money(paid.get("tds") or zero)
        settlement = settlements.get(trip.pk)
        liability = money(settlement.total_vendor_gross_cost if settlement else freight)

        total_freight += freight
        total_advance += advance
        total_liability += liability
        total_cash += cash
        total_tds += tds
        total_remaining += max(zero, money(liability - cash - tds))

    return {
        "total_freight_100": money(total_freight),
        "total_advance_amount": money(total_advance),
        "freight_balance_after_advance": money(total_freight - total_advance),
        "total_vendor_liability": money(total_liability),
        "cash_paid": money(total_cash),
        "tds_deducted": money(total_tds),
        "remaining_to_pay": money(total_remaining),
    }


class PaymentsPermission(RolePermission):
    read_capability = "payments.read"
    write_capability = "payments.write"


class PaymentViewSet(viewsets.ModelViewSet):
    permission_classes = [PaymentsPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = FinancePaymentTransaction.objects.select_related("vendor", "created_by", "paid_by").prefetch_related("allocations__trip", "allocations__approval_item__batch").order_by("-payment_date", "-id")
        if getattr(self.request.user, "role", "") == User.Role.TRANSPORTER:
            queryset = queryset.filter(vendor_id=self.request.user.vendor_id)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(payment_no__icontains=search)
                | Q(utr_reference__icontains=search)
                | Q(vendor__display_name__icontains=search)
                | Q(allocations__trip__trip_no__icontains=search)
            )
        vendor = self.request.query_params.get("vendor")
        status_filter = self.request.query_params.get("status")
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if vendor:
            queryset = queryset.filter(vendor_id=vendor)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if date_from:
            queryset = queryset.filter(payment_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(payment_date__lte=date_to)
        return queryset.distinct()

    def get_serializer_class(self):
        return PaymentCreateSerializer if self.action == "create" else PaymentSerializer

    def create(self, request, *args, **kwargs):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        vendor = Vendor.objects.get(pk=data.pop("vendor"))
        bank_id = data.pop("bank_account", None)
        bank = VendorBankAccount.objects.get(pk=bank_id) if bank_id else None
        proof_id = data.pop("proof_document", None)
        proof = Document.objects.get(pk=proof_id) if proof_id else None
        payment = create_paid_payment(
            actor=request.user,
            vendor=vendor,
            bank_account=bank,
            proof_document=proof,
            request_id=getattr(request, "request_id", ""),
            **data,
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payment = reverse_payment(
            actor=request.user,
            payment=self.get_object(),
            reason=request.data.get("reason", ""),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(PaymentSerializer(payment).data)


class FinancePendingView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        if not has_capability(request.user, "payments.write"):
            return Response({"detail": "Finance permission is required"}, status=403)
        items = list(
            PaymentApprovalItem.objects.filter(item_status=PaymentApprovalItem.Status.APPROVED)
            .select_related("vendor", "trip", "trip__vehicle", "trip__driver", "trip__client", "batch")
            .order_by("batch__updated_at", "id")
        )
        eligible_items = []
        for item in items:
            paid = paid_totals(item)
            if item.net_requested - paid["net"] > 0:
                eligible_items.append((item, paid))

        vendor_ids = {item.vendor_id for item, _paid in eligible_items}
        trip_ids = {item.trip_id for item, _paid in eligible_items}
        driver_ids = {item.trip.driver_id for item, _paid in eligible_items}
        bank_accounts = list(
            VendorBankAccount.objects.filter(vendor_id__in=vendor_ids).order_by("vendor_id", "-active", "id")
        )
        bank_ids = {account.pk for account in bank_accounts}
        documents = Document.objects.filter(scan_status="CLEAN").filter(
            Q(object_type="vendor", object_id__in=[str(value) for value in vendor_ids])
            | Q(object_type="driver", object_id__in=[str(value) for value in driver_ids])
            | Q(object_type="trip", object_id__in=[str(value) for value in trip_ids])
            | Q(object_type="vendor_bank_account", object_id__in=[str(value) for value in bank_ids])
        )
        documents_by_owner = {}
        for document in documents:
            documents_by_owner.setdefault((document.object_type, document.object_id), []).append(
                _document_payload(document, request)
            )

        groups = {}
        for item, paid in eligible_items:
            remaining_net = item.net_requested - paid["net"]
            group = groups.setdefault(
                item.vendor_id,
                {
                    "vendor_id": item.vendor_id,
                    "vendor_code": item.vendor.vendor_code,
                    "vendor_name": item.vendor.display_name,
                    "vendor_legal_name": item.vendor.legal_name,
                    "vendor_email": item.vendor.email,
                    "vendor_phone": item.vendor.primary_phone,
                    "vendor_documents": documents_by_owner.get(("vendor", str(item.vendor_id)), []),
                    "bank_accounts": [],
                    "total_net": Decimal("0"),
                    "items": [],
                },
            )
            group["total_net"] += remaining_net
            group["items"].append(
                {
                    "approval_item_id": item.pk,
                    "approval_id": item.batch_id,
                    "approval_no": item.batch.approval_no,
                    "trip_id": item.trip_id,
                    "trip_no": item.trip.trip_no,
                    "route": f"{item.trip.origin} → {item.trip.destination}",
                    "client_name": item.trip.client.name,
                    "deployment_date": item.trip.deployment_date,
                    "trip_created_at": item.trip.created_at,
                    "approved_at": item.batch.updated_at,
                    "vehicle_no": item.trip.vehicle_registration_snapshot,
                    "vehicle_type": item.trip.vehicle_type_snapshot,
                    "driver_id": item.trip.driver_id,
                    "driver_name": item.trip.driver_name_snapshot,
                    "driver_phone": item.trip.driver_phone_snapshot,
                    "driver_documents": documents_by_owner.get(("driver", str(item.trip.driver_id)), []),
                    "trip_documents": documents_by_owner.get(("trip", str(item.trip_id)), []),
                    "freight_100": item.freight_rate_snapshot,
                    "advance_percent": item.advance_percent,
                    "advance_amount": item.freight_advance_gross,
                    "freight_balance_after_advance": money(
                        item.freight_rate_snapshot - item.freight_advance_gross
                    ),
                    "remaining_gross": item.gross_requested - paid["gross"],
                    "remaining_tds": item.tds_this_request - paid["tds"],
                    "remaining_net": remaining_net,
                }
            )
        for account in bank_accounts:
            group = groups.get(account.vendor_id)
            if not group:
                continue
            proofs = documents_by_owner.get(("vendor_bank_account", str(account.pk)), [])
            group["bank_accounts"].append(
                {
                    "id": account.pk,
                    "bank_name": account.bank_name,
                    "account_holder": account.account_holder,
                    "masked_account_number": account.masked_account_number,
                    "ifsc_code": account.ifsc_code,
                    "active": account.active,
                    "created_at": account.created_at,
                    "cancelled_cheque_uploaded": bool(proofs),
                    "cancelled_cheque_documents": proofs,
                }
            )
        return Response(list(groups.values()))


class TDSEntryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TDSEntrySerializer
    permission_classes = [PaymentsPermission]

    def get_queryset(self):
        queryset = TDSEntry.objects.select_related("vendor", "trip", "payment").order_by("-deduction_date", "-id")
        if getattr(self.request.user, "role", "") == User.Role.TRANSPORTER:
            queryset = queryset.filter(vendor_id=self.request.user.vendor_id)
        return queryset


class SettlementPermission(RolePermission):
    read_capability = "payments.read"
    write_capability = "trips.write"

    def has_permission(self, request, view):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return has_capability(request.user, "payments.read") or has_capability(request.user, "trips.read")
        return has_capability(request.user, "trips.write") or has_capability(request.user, "*")


class FinalTripSettlementViewSet(viewsets.ModelViewSet):
    serializer_class = FinalTripSettlementSerializer
    permission_classes = [SettlementPermission]
    queryset = FinalTripSettlement.objects.select_related("trip", "trip__vendor", "settlement_approval").order_by("-created_at")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            queryset = queryset.filter(trip__vendor_id=self.request.user.vendor_id)
        trip_id = self.request.query_params.get("trip")
        return queryset.filter(trip_id=trip_id) if trip_id else queryset

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        settlement = save_settlement(
            actor=request.user,
            trip=data["trip"],
            final_freight=data["final_freight"],
            additive_charges=data.get("additive_charges", 0),
            vendor_deductions=data.get("vendor_deductions", 0),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(self.get_serializer(settlement).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        current = self.get_object()
        values = {
            "final_freight": request.data.get("final_freight", current.final_freight),
            "additive_charges": request.data.get("additive_charges", current.additive_charges),
            "vendor_deductions": request.data.get("vendor_deductions", current.vendor_deductions),
        }
        settlement = save_settlement(
            actor=request.user,
            trip=current.trip,
            request_id=getattr(request, "request_id", ""),
            **values,
        )
        return Response(self.get_serializer(settlement).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        settlement = submit_settlement(
            actor=request.user,
            settlement=self.get_object(),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(self.get_serializer(settlement).data)

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        settlement = finalize_settlement(
            actor=request.user,
            settlement=self.get_object(),
            request_id=getattr(request, "request_id", ""),
        )
        return Response(self.get_serializer(settlement).data)


class ClientBillingViewSet(viewsets.ModelViewSet):
    serializer_class = ClientBillingSerializer
    permission_classes = [SettlementPermission]
    queryset = ClientBilling.objects.select_related("trip", "client", "trip__vendor").order_by("-created_at")
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            return queryset.none()
        trip_id = self.request.query_params.get("trip")
        return queryset.filter(trip_id=trip_id) if trip_id else queryset

    def perform_create(self, serializer):
        trip = serializer.validated_data["trip"]
        billing = serializer.save(client=trip.client, created_by=self.request.user)
        trip.client_billing_amount = billing.billing_amount
        trip.save(update_fields=["client_billing_amount", "updated_at"])
        from audit.models import record_audit

        record_audit(actor=self.request.user, action="CLIENT_BILLING_CREATED", instance=billing, after=serializer.data, request_id=getattr(self.request, "request_id", ""))

    def perform_update(self, serializer):
        billing = serializer.save()
        billing.trip.client_billing_amount = billing.billing_amount
        billing.trip.save(update_fields=["client_billing_amount", "updated_at"])


class VendorLedgerView(APIView):
    @extend_schema(responses=dict)
    def get(self, request, vendor_id):
        if request.user.role == User.Role.TRANSPORTER and request.user.vendor_id != vendor_id:
            return Response({"detail": "Vendor isolation policy denied access"}, status=403)
        vendor = Vendor.objects.get(pk=vendor_id)
        allocations = PaymentAllocation.objects.filter(payment__vendor=vendor).select_related("payment", "trip", "approval_item__batch").order_by("payment__payment_date", "id")
        financial = _financial_position(
            Trip.objects.filter(vendor=vendor).exclude(status=Trip.Status.CANCELLED)
        )
        entries = []
        approved_total = Decimal("0")
        cash_paid = Decimal("0")
        tds = Decimal("0")
        for item in PaymentApprovalItem.objects.filter(vendor=vendor, item_status=PaymentApprovalItem.Status.APPROVED):
            approved_total += item.gross_requested
        for row in allocations:
            base_entry = {
                "date": row.payment.payment_date,
                "timestamp": row.payment.paid_at or row.payment.created_at,
                "trip_no": row.trip.trip_no,
                "approval_no": row.approval_item.batch.approval_no,
                "payment_no": row.payment.payment_no,
                "utr": row.payment.utr_reference,
                "status": row.payment.status,
            }
            if row.payment.status == FinancePaymentTransaction.Status.REVERSED:
                entries.extend(
                    [
                        {
                            **base_entry,
                            "type": "PAYMENT",
                            "gross": row.gross_amount_allocated,
                            "tds": row.tds_allocated,
                            "cash": row.net_cash_allocated,
                        },
                        {
                            **base_entry,
                            "type": "PAYMENT_REVERSAL",
                            "gross": -row.gross_amount_allocated,
                            "tds": -row.tds_allocated,
                            "cash": -row.net_cash_allocated,
                        },
                    ]
                )
            elif row.payment.status == FinancePaymentTransaction.Status.PAID:
                cash_paid += row.net_cash_allocated
                tds += row.tds_allocated
                entries.append(
                    {
                        **base_entry,
                        "type": "PAYMENT",
                        "gross": row.gross_amount_allocated,
                        "tds": row.tds_allocated,
                        "cash": row.net_cash_allocated,
                    }
                )
        approved_remaining = max(Decimal("0.00"), approved_total - cash_paid - tds)
        return Response({
            "vendor_id": vendor.pk,
            "vendor_name": vendor.display_name,
            "approved_gross": approved_total,
            "approved_remaining": approved_remaining,
            "tds": tds,
            "cash_paid": cash_paid,
            "unpaid_gross": approved_remaining,
            **financial,
            "entries": entries,
        })


class TripLedgerView(APIView):
    @extend_schema(responses=dict)
    def get(self, request, trip_id):
        queryset = Trip.objects.select_related("vendor", "client").filter(pk=trip_id)
        if request.user.role == User.Role.TRANSPORTER:
            queryset = queryset.filter(vendor_id=request.user.vendor_id)
        trip = queryset.first()
        if not trip:
            return Response({"detail": "Not found"}, status=404)
        items = trip.approval_items.exclude(item_status=PaymentApprovalItem.Status.SUPERSEDED)
        allocations = trip.payment_allocations.select_related("payment", "approval_item__batch")
        approved_gross = items.filter(item_status=PaymentApprovalItem.Status.APPROVED).aggregate(total=Sum("gross_requested"))["total"] or 0
        cash = sum((a.net_cash_allocated for a in allocations if a.payment.status == FinancePaymentTransaction.Status.PAID), Decimal("0"))
        tds = sum((a.tds_allocated for a in allocations if a.payment.status == FinancePaymentTransaction.Status.PAID), Decimal("0"))
        settlement = getattr(trip, "final_settlement", None)
        billing = getattr(trip, "billing", None)
        profitability = None
        if billing:
            from approvals.calculations import calculate_profitability

            profitability = calculate_profitability(
                client_billing_amount=billing.billing_amount,
                final_vendor_gross_cost=settlement.total_vendor_gross_cost if settlement else trip.vendor_freight_rate,
                internal_costs=billing.internal_trip_costs,
            )
        transporter_view = request.user.role == User.Role.TRANSPORTER
        freight_100 = money(trip.vendor_freight_rate)
        advance_amount = money(freight_100 * trip.advance_percent / Decimal("100"))
        total_liability = money(settlement.total_vendor_gross_cost if settlement else freight_100)
        remaining_to_pay = max(Decimal("0.00"), money(total_liability - tds - cash))
        return Response({
            "trip_id": trip.pk,
            "trip_no": trip.trip_no,
            "vendor": trip.vendor.display_name,
            "created_at": trip.created_at,
            "updated_at": trip.updated_at,
            "agreed_freight": trip.vendor_freight_rate,
            "freight_100": freight_100,
            "advance_percent": trip.advance_percent,
            "advance_amount": advance_amount,
            "freight_balance_after_advance": money(freight_100 - advance_amount),
            "approved_gross": approved_gross,
            "tds_deducted": tds,
            "cash_paid": cash,
            "remaining_approved": max(Decimal("0.00"), Decimal(approved_gross) - tds - cash),
            "total_vendor_liability": total_liability,
            "remaining_to_pay": remaining_to_pay,
            "client_billing": None if transporter_view else trip.client_billing_amount,
            "final_vendor_cost": settlement.total_vendor_gross_cost if settlement else None,
            "remaining_cash_payable": remaining_to_pay,
            "billing_status": "" if transporter_view else (billing.payment_status if billing else "NOT_CREATED"),
            "gross_profit": None if transporter_view or not profitability else profitability["gross_profit"],
            "margin_percent": None if transporter_view or not profitability else profitability["margin_percent"],
            "charges": [
                {
                    "type": charge.charge_type,
                    "description": charge.description,
                    "amount": charge.amount,
                    "direction": charge.direction,
                    "source": charge.source,
                }
                for charge in trip.charges.all()
            ],
            "events": PaymentSerializer([a.payment for a in allocations], many=True).data,
        })


class DashboardView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        today = timezone.localdate()
        paid = FinancePaymentTransaction.objects.filter(status=FinancePaymentTransaction.Status.PAID)
        if request.user.role == User.Role.TRANSPORTER:
            paid = paid.filter(vendor_id=request.user.vendor_id)
        trips = Trip.objects.all()
        items = PaymentApprovalItem.objects.all()
        if request.user.role == User.Role.TRANSPORTER:
            trips = trips.filter(vendor_id=request.user.vendor_id)
            items = items.filter(vendor_id=request.user.vendor_id)
        unpaid = Decimal("0")
        for item in items.filter(item_status=PaymentApprovalItem.Status.APPROVED):
            unpaid += max(Decimal("0"), item.net_requested - paid_totals(item)["net"])
        unsettled_cash = (
            PaymentAllocation.objects.filter(
                trip__in=trips.exclude(settlement_status="SETTLED"), payment__status="PAID"
            ).aggregate(total=Sum("net_cash_allocated"))["total"]
            or 0
        )
        financial = _financial_position(trips.exclude(status=Trip.Status.CANCELLED))
        gross_margin = Decimal("0")
        for billing in ClientBilling.objects.filter(trip__in=trips).select_related("trip"):
            settlement = getattr(billing.trip, "final_settlement", None)
            cost = settlement.total_vendor_gross_cost if settlement else billing.trip.vendor_freight_rate
            gross_margin += billing.billing_amount - cost - billing.internal_trip_costs
        transporter_view = request.user.role == User.Role.TRANSPORTER
        return Response({
            "trips_today": trips.filter(deployment_date=today).count(),
            "vehicles_deployed": trips.filter(deployment_date=today).values("vehicle_id").distinct().count(),
            "awaiting_vehicle": trips.filter(vehicle__isnull=True).count(),
            "pending_approvals": items.filter(item_status=PaymentApprovalItem.Status.PENDING).aggregate(total=Sum("net_requested"))["total"] or 0,
            "approved_not_paid": unpaid,
            "paid_today": paid.filter(payment_date=today).aggregate(total=Sum("net_paid_amount"))["total"] or 0,
            "total_cash_paid": financial["cash_paid"],
            "total_tds_deducted": financial["tds_deducted"],
            "total_gross_accounted": money(financial["cash_paid"] + financial["tds_deducted"]),
            "total_freight_100": financial["total_freight_100"],
            "total_advance_amount": financial["total_advance_amount"],
            "freight_balance_after_advance": financial["freight_balance_after_advance"],
            "total_remaining_to_pay": financial["remaining_to_pay"],
            "advance_cash_paid_unsettled": unsettled_cash,
            "remaining_vendor_payable": financial["remaining_to_pay"],
            "tds_month_to_date": TDSEntry.objects.filter(trip__in=trips, deduction_date__year=today.year, deduction_date__month=today.month, status="POSTED").aggregate(total=Sum("tds_amount"))["total"] or 0,
            "trips_pending_settlement": trips.filter(status__in=[Trip.Status.DELIVERED, Trip.Status.SETTLEMENT_PENDING, Trip.Status.SETTLEMENT_APPROVAL_PENDING]).count(),
            "pod_pending": trips.filter(pod_status="PENDING").count(),
            "billing_pending": 0 if transporter_view else trips.filter(status__in=[Trip.Status.DELIVERED, Trip.Status.SETTLEMENT_PENDING, Trip.Status.SETTLEMENT_APPROVAL_PENDING, Trip.Status.SETTLED]).exclude(billing__payment_status=ClientBilling.Status.RECEIVED).count(),
            "gross_margin": 0 if transporter_view else gross_margin,
        })


class ReportCatalogView(APIView):
    @extend_schema(operation_id="report_catalog", responses=dict)
    def get(self, request):
        if not has_capability(request.user, "reports.read") and not has_capability(request.user, "*"):
            return Response({"detail": "Reporting permission is required"}, status=403)
        return Response([{"slug": slug, "name": name} for slug, name in REPORT_CATALOG.items()])


class ReportView(APIView):
    @extend_schema(operation_id="report_detail", responses=dict)
    def get(self, request, slug):
        if not has_capability(request.user, "reports.read") and not has_capability(request.user, "*"):
            return Response({"detail": "Reporting permission is required"}, status=403)
        try:
            report = build_report(slug, request.query_params)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=404)
        export_format = request.query_params.get("format")
        if export_format == "csv":
            response = HttpResponse(export_csv(report), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{slug}.csv"'
            return response
        if export_format == "xlsx":
            response = HttpResponse(
                export_xlsx(report, REPORT_CATALOG[slug]),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="{slug}.xlsx"'
            return response
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(200, max(1, int(request.query_params.get("page_size", 50))))
        start = (page - 1) * page_size
        return Response(
            {
                "slug": slug,
                "name": REPORT_CATALOG[slug],
                "columns": report.columns,
                "count": len(report.rows),
                "page": page,
                "page_size": page_size,
                "rows": report.rows[start : start + page_size],
                "totals": report.totals,
            }
        )
