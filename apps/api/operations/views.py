from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import RolePermission, has_capability
from approvals.models import PaymentApprovalItem
from approvals.services import calculate_trip_advance
from audit.models import record_audit
from core.files import inspect_upload

from .models import (
    Client,
    Document,
    Driver,
    Indent,
    Trip,
    TripRecovery,
    Vehicle,
    Vendor,
    VendorBankAccount,
    VendorContact,
)
from .serializers import (
    ClientSerializer,
    DocumentSerializer,
    DriverSerializer,
    IndentSerializer,
    TripChargeSerializer,
    TripRecoverySerializer,
    TripSerializer,
    VehicleSerializer,
    VendorBankAccountSerializer,
    VendorContactSerializer,
    VendorSerializer,
)


class MastersPermission(RolePermission):
    read_capability = "masters.read"
    write_capability = "masters.write"


class BankAccountPermission(RolePermission):
    def has_permission(self, request, view):
        allowed_roles = {User.Role.ADMIN, User.Role.FINANCE, User.Role.OPERATIONS}
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            allowed_roles.add(User.Role.MANAGEMENT)
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in allowed_roles
        )


class TripsPermission(RolePermission):
    read_capability = "trips.read"
    write_capability = "trips.write"


class DocumentPermission(RolePermission):
    def has_permission(self, request, view):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return any(
                has_capability(request.user, capability)
                for capability in ("trips.read", "payments.read", "approvals.read", "own.read")
            )
        object_type = request.data.get("object_type", "")
        required = {
            "trip": "trips.write",
            "approval": "comments.write",
            "comment": "comments.write",
            "payment": "payments.write",
            "vendor": "masters.write",
            "driver": "masters.write",
        }.get(object_type)
        if object_type == "vendor_bank_account":
            return request.user.role in {User.Role.ADMIN, User.Role.FINANCE, User.Role.OPERATIONS}
        return bool(required and has_capability(request.user, required)) or has_capability(request.user, "*")


class AuditedModelViewSet(viewsets.ModelViewSet):
    def perform_create(self, serializer):
        instance = serializer.save()
        record_audit(actor=self.request.user, action="CREATED", instance=instance, after=serializer.data, request_id=getattr(self.request, "request_id", ""))

    def perform_update(self, serializer):
        before = type(serializer.instance).__name__
        instance = serializer.save()
        record_audit(actor=self.request.user, action="UPDATED", instance=instance, before={"object": before}, after=serializer.data, request_id=getattr(self.request, "request_id", ""))


class ClientViewSet(AuditedModelViewSet):
    queryset = Client.objects.all().order_by("name")
    serializer_class = ClientSerializer
    permission_classes = [MastersPermission]
    search_fields = ["code", "name"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            return queryset.filter(trips__vendor_id=self.request.user.vendor_id).distinct()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        active = self.request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(active=active == "true")
        return queryset


class VendorViewSet(AuditedModelViewSet):
    serializer_class = VendorSerializer
    permission_classes = [MastersPermission]
    search_fields = ["vendor_code", "display_name", "legal_name"]

    def get_queryset(self):
        queryset = Vendor.objects.prefetch_related("contacts", "bank_accounts", "vehicles").order_by("display_name")
        if getattr(self.request.user, "role", "") == User.Role.TRANSPORTER:
            return queryset.filter(pk=self.request.user.vendor_id)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(vendor_code__icontains=search)
                | Q(display_name__icontains=search)
                | Q(legal_name__icontains=search)
                | Q(primary_phone__icontains=search)
                | Q(email__icontains=search)
            )
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset


class VendorContactViewSet(AuditedModelViewSet):
    serializer_class = VendorContactSerializer
    permission_classes = [MastersPermission]
    queryset = VendorContact.objects.select_related("vendor").order_by("vendor", "name")

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            return queryset.filter(vendor_id=self.request.user.vendor_id)
        return queryset


class VendorBankAccountViewSet(AuditedModelViewSet):
    serializer_class = VendorBankAccountSerializer
    permission_classes = [BankAccountPermission]
    queryset = VendorBankAccount.objects.select_related("vendor").order_by("vendor", "bank_name")

    def get_queryset(self):
        if self.request.user.role not in {User.Role.ADMIN, User.Role.FINANCE, User.Role.OPERATIONS, User.Role.MANAGEMENT}:
            return VendorBankAccount.objects.none()
        return super().get_queryset()


class VehicleViewSet(AuditedModelViewSet):
    queryset = Vehicle.objects.select_related("vendor").order_by("registration_no")
    serializer_class = VehicleSerializer
    permission_classes = [MastersPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            queryset = queryset.filter(vendor_id=self.request.user.vendor_id)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(registration_no__icontains=search)
                | Q(vehicle_type__icontains=search)
                | Q(vendor__display_name__icontains=search)
            )
        vendor = self.request.query_params.get("vendor")
        if vendor:
            queryset = queryset.filter(vendor_id=vendor)
        active = self.request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(active=active == "true")
        return queryset


class DriverViewSet(AuditedModelViewSet):
    queryset = Driver.objects.select_related("vendor").order_by("name")
    serializer_class = DriverSerializer
    permission_classes = [MastersPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            queryset = queryset.filter(vendor_id=self.request.user.vendor_id)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(vendor__display_name__icontains=search)
            )
        vendor = self.request.query_params.get("vendor")
        if vendor:
            queryset = queryset.filter(vendor_id=vendor)
        active = self.request.query_params.get("active")
        if active in {"true", "false"}:
            queryset = queryset.filter(active=active == "true")
        return queryset


class IndentViewSet(AuditedModelViewSet):
    queryset = Indent.objects.select_related("client").prefetch_related("assigned_trips").order_by("-indent_date", "indent_no")
    serializer_class = IndentSerializer
    permission_classes = [TripsPermission]
    search_fields = [
        "indent_no", "challan_no", "origin", "destination", "ship_to_party_code",
        "ship_to_party_name", "destination_state", "pin_code", "item",
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            queryset = queryset.filter(assigned_trips__vendor_id=self.request.user.vendor_id).distinct()
        for field in ("status", "client"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field if field == "status" else "client_id": value})
        assigned = self.request.query_params.get("assigned")
        if assigned == "false":
            queryset = queryset.filter(assigned_trips__isnull=True)
        elif assigned == "true":
            queryset = queryset.filter(assigned_trips__isnull=False).distinct()
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(indent_no__icontains=search)
                | Q(challan_no__icontains=search)
                | Q(origin__icontains=search)
                | Q(destination__icontains=search)
                | Q(ship_to_party_code__icontains=search)
                | Q(ship_to_party_name__icontains=search)
                | Q(item__icontains=search)
            )
        branch = self.request.query_params.get("branch")
        if branch:
            queryset = queryset.filter(branch__iexact=branch)
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(indent_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(indent_date__lte=date_to)
        return queryset


class TripViewSet(AuditedModelViewSet):
    serializer_class = TripSerializer
    permission_classes = [TripsPermission]
    search_fields = ["trip_no", "indent__indent_no", "indents__challan_no", "indents__ship_to_party_name", "vehicle_registration_snapshot", "vendor__display_name", "origin", "destination"]

    def get_queryset(self):
        queryset = Trip.objects.select_related("client", "indent", "vendor", "vehicle", "driver").prefetch_related("charges", "tds_entries", "indent_links__indent__assigned_trips").order_by("-deployment_date", "-id")
        if getattr(self.request.user, "role", "") == User.Role.TRANSPORTER:
            queryset = queryset.filter(vendor_id=self.request.user.vendor_id)
        for field in ("status", "vendor", "client"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field if field == "status" else f"{field}_id": value})
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(trip_no__icontains=search)
                | Q(indent__indent_no__icontains=search)
                | Q(indents__challan_no__icontains=search)
                | Q(indents__ship_to_party_name__icontains=search)
                | Q(vehicle_registration_snapshot__icontains=search)
                | Q(vehicle_type_snapshot__icontains=search)
                | Q(vendor__display_name__icontains=search)
                | Q(origin__icontains=search)
                | Q(destination__icontains=search)
            )
        branch = self.request.query_params.get("branch")
        if branch:
            queryset = queryset.filter(branch__iexact=branch)
        vehicle_type = self.request.query_params.get("vehicle_type")
        if vehicle_type:
            queryset = queryset.filter(vehicle_type_snapshot__icontains=vehicle_type)
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(deployment_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(deployment_date__lte=date_to)
        return queryset.prefetch_related("approval_items__batch").distinct()

    def perform_update(self, serializer):
        if serializer.instance.status == Trip.Status.SETTLED:
            raise serializers.ValidationError("Settled trips are locked")
        protected = {"vendor", "vehicle", "vendor_freight_rate", "advance_percent", "client", "indent", "indent_ids"}
        active_snapshot = serializer.instance.approval_items.exclude(
            item_status__in=[
                PaymentApprovalItem.Status.REJECTED,
                PaymentApprovalItem.Status.CHANGES_REQUESTED,
                PaymentApprovalItem.Status.SUPERSEDED,
            ]
        )
        if protected.intersection(serializer.validated_data) and active_snapshot.exists():
            raise serializers.ValidationError(
                "Financial fields with an active approval snapshot are locked; use the revision workflow"
            )
        super().perform_update(serializer)

    @action(detail=True, methods=["get"], url_path="indent-suggestions")
    def indent_suggestions(self, request, pk=None):
        trip = self.get_object()
        queryset = (
            Indent.objects.filter(client=trip.client)
            .exclude(status=Indent.Status.CANCELLED)
            .exclude(assigned_trips=trip)
            .select_related("client")
            .prefetch_related("assigned_trips")
            .order_by("-challan_datetime", "-indent_date", "indent_no")[:100]
        )
        suggestions = []
        for indent in queryset:
            score = 0
            reasons = []
            if indent.origin.strip().lower() == trip.origin.strip().lower():
                score += 3
                reasons.append("same origin")
            if indent.destination.strip().lower() == trip.destination.strip().lower():
                score += 3
                reasons.append("same destination")
            if indent.indent_date == trip.deployment_date:
                score += 2
                reasons.append("same date")
            if indent.required_vehicle_type and indent.required_vehicle_type == trip.vehicle_type_snapshot:
                score += 1
                reasons.append("same vehicle type")
            suggestions.append((score, indent, reasons))
        suggestions.sort(key=lambda value: (-value[0], -value[1].indent_date.toordinal(), value[1].indent_no))
        data = []
        for score, indent, reasons in suggestions[:20]:
            row = IndentSerializer(indent, context={"request": request}).data
            row["match_score"] = score
            row["match_reasons"] = reasons
            data.append(row)
        return Response(data)

    @action(detail=True, methods=["get"])
    def calculate(self, request, pk=None):
        return Response(calculate_trip_advance(self.get_object()).as_dict())

    @action(detail=True, methods=["post"])
    def charges(self, request, pk=None):
        trip = self.get_object()
        if trip.status in {Trip.Status.SETTLED, Trip.Status.CANCELLED, Trip.Status.CANCELLED_WITH_PAYMENT}:
            return Response({"detail": "Charges cannot be added to a closed trip"}, status=400)
        if trip.approval_items.exclude(
            item_status__in=[
                PaymentApprovalItem.Status.REJECTED,
                PaymentApprovalItem.Status.CHANGES_REQUESTED,
                PaymentApprovalItem.Status.SUPERSEDED,
            ]
        ).exists():
            return Response(
                {"detail": "Charges are locked while an approval snapshot is active"},
                status=400,
            )
        serializer = TripChargeSerializer(data={**request.data, "trip": trip.pk})
        serializer.is_valid(raise_exception=True)
        charge = serializer.save(created_by=request.user)
        record_audit(actor=request.user, action="TRIP_CHARGE_CREATED", instance=charge, after=serializer.data, request_id=getattr(request, "request_id", ""))
        return Response(TripChargeSerializer(charge).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        trip = self.get_object()
        if not request.data.get("reason", "").strip():
            return Response({"detail": "Revision reason is required"}, status=400)
        allowed = {"vendor", "vehicle", "driver", "vendor_freight_rate", "advance_percent"}
        if trip.payment_allocations.filter(payment__status="PAID").exists():
            return Response(
                {"detail": "A paid trip cannot be financially revised; use settlement or recovery."},
                status=400,
            )
        if trip.approval_items.filter(
            item_status__in=[PaymentApprovalItem.Status.DRAFT, PaymentApprovalItem.Status.PENDING]
        ).exists():
            return Response(
                {"detail": "An active approval must be sent back or cancelled before revision."},
                status=400,
            )
        changes = {key: value for key, value in request.data.items() if key in allowed}
        serializer = self.get_serializer(trip, data=changes, partial=True)
        serializer.is_valid(raise_exception=True)
        old = {key: str(getattr(trip, f"{key}_id", getattr(trip, key, ""))) for key in changes}
        next_status = Trip.Status.READY if trip.status in {Trip.Status.DRAFT, Trip.Status.READY, Trip.Status.ADVANCE_APPROVAL_PENDING, Trip.Status.ADVANCE_APPROVED} else trip.status
        trip = serializer.save(status=next_status)
        approved_items = trip.approval_items.filter(item_status=PaymentApprovalItem.Status.APPROVED)
        batch_ids = list(approved_items.values_list("batch_id", flat=True))
        approved_items.update(item_status=PaymentApprovalItem.Status.SUPERSEDED)
        from approvals.models import PaymentApprovalBatch
        from approvals.services import refresh_batch_status_from_items

        for batch in PaymentApprovalBatch.objects.filter(pk__in=batch_ids):
            refresh_batch_status_from_items(batch)
        record_audit(actor=request.user, action="TRIP_FINANCIAL_REVISION", instance=trip, before=old, after={**changes, "reason": request.data["reason"]}, request_id=getattr(request, "request_id", ""))
        return Response(self.get_serializer(trip).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def deliver(self, request, pk=None):
        trip = Trip.objects.select_for_update().get(pk=self.get_object().pk)
        if trip.status in {Trip.Status.CANCELLED, Trip.Status.CANCELLED_WITH_PAYMENT, Trip.Status.SETTLED}:
            return Response({"detail": "This trip cannot be marked delivered"}, status=400)
        if trip.actual_delivery_at:
            return Response(self.get_serializer(trip).data)
        trip.status = Trip.Status.DELIVERED
        trip.actual_delivery_at = timezone.now()
        trip.settlement_status = "PENDING"
        trip.save(update_fields=["status", "actual_delivery_at", "settlement_status", "updated_at"])
        record_audit(actor=request.user, action="TRIP_DELIVERED", instance=trip, after={"actual_delivery_at": trip.actual_delivery_at}, request_id=getattr(request, "request_id", ""))
        from integrations.services import emit_event

        emit_event("SETTLEMENT_PENDING", instance=trip, actor=request.user)
        return Response(self.get_serializer(trip).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, pk=None):
        trip = Trip.objects.select_for_update().get(pk=self.get_object().pk)
        if trip.status == Trip.Status.SETTLED:
            return Response({"detail": "Settled trips cannot be cancelled"}, status=400)
        paid = trip.payment_allocations.filter(payment__status="PAID").aggregate(total=Sum("net_cash_allocated"))["total"] or 0
        if paid:
            method = request.data.get("resolution_method", "")
            reason = request.data.get("reason", "").strip()
            if method not in TripRecovery.Resolution.values or not reason:
                return Response({"detail": "Paid-trip cancellation requires a resolution method and reason"}, status=400)
            TripRecovery.objects.update_or_create(
                trip=trip,
                defaults={
                    "amount": paid,
                    "resolution_method": method,
                    "reference": request.data.get("reference", ""),
                    "reason": reason,
                    "created_by": request.user,
                },
            )
            trip.status = Trip.Status.CANCELLED_WITH_PAYMENT
        else:
            trip.status = Trip.Status.CANCELLED
        trip.save(update_fields=["status", "updated_at"])
        # Undecided approval lines would otherwise block their batch forever, because
        # decisions on cancelled trips are refused.
        open_items = trip.approval_items.filter(
            item_status=PaymentApprovalItem.Status.PENDING,
            batch__status__in=["PENDING", "PARTIALLY_APPROVED"],
        )
        batch_ids = list(open_items.values_list("batch_id", flat=True))
        open_items.update(item_status=PaymentApprovalItem.Status.SUPERSEDED, approver_note="Trip cancelled before a decision was recorded")
        from approvals.models import PaymentApprovalBatch
        from approvals.services import refresh_batch_status_from_items

        for batch in PaymentApprovalBatch.objects.filter(pk__in=batch_ids):
            refresh_batch_status_from_items(batch)
        record_audit(actor=request.user, action="TRIP_CANCELLED", instance=trip, after={"status": trip.status, "paid": str(paid)}, request_id=getattr(request, "request_id", ""))
        return Response(self.get_serializer(trip).data)


# What the in-app viewer can render itself. Anything else - a spreadsheet, an
# audio note - is handed back as a download rather than dropped into an iframe.
INLINE_PREVIEW_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.none()
    serializer_class = DocumentSerializer
    permission_classes = [DocumentPermission]
    parser_classes = [MultiPartParser, FormParser]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = Document.objects.select_related("uploaded_by").order_by("-created_at")
        can_read_sensitive = (
            has_capability(self.request.user, "sensitive.read")
            or has_capability(self.request.user, "masters.write")
        )
        if not can_read_sensitive:
            queryset = queryset.exclude(
                Q(kind__in={
                    Document.Kind.AADHAAR,
                    Document.Kind.PAN,
                    Document.Kind.DRIVING_LICENSE,
                    Document.Kind.CANCELLED_CHEQUE,
                })
                | Q(object_type__in={"vendor", "driver", "vendor_bank_account"})
            )
        if self.request.user.role == User.Role.TRANSPORTER:
            trip_ids = Trip.objects.filter(vendor_id=self.request.user.vendor_id).values_list("id", flat=True)
            from payments.models import FinancePaymentTransaction

            payment_ids = FinancePaymentTransaction.objects.filter(vendor_id=self.request.user.vendor_id).values_list("id", flat=True)
            queryset = queryset.filter(
                Q(object_type="trip", object_id__in=[str(value) for value in trip_ids])
                | Q(object_type="payment", object_id__in=[str(value) for value in payment_ids])
            )
        for field in ("object_type", "object_id", "kind"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def perform_create(self, serializer):
        uploaded = self.request.FILES["file"]
        try:
            inspection = inspect_upload(uploaded)
        except ValueError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
        object_type = serializer.validated_data["object_type"]
        object_id = serializer.validated_data["object_id"]
        if object_type not in {"trip", "approval", "payment", "comment", "vendor", "driver", "vendor_bank_account"}:
            raise serializers.ValidationError({"object_type": "Unsupported document context"})
        from approvals.models import Comment, PaymentApprovalBatch
        from payments.models import FinancePaymentTransaction

        model = {
            "trip": Trip,
            "approval": PaymentApprovalBatch,
            "payment": FinancePaymentTransaction,
            "comment": Comment,
            "vendor": Vendor,
            "driver": Driver,
            "vendor_bank_account": VendorBankAccount,
        }[object_type]
        if not model.objects.filter(pk=object_id).exists():
            raise serializers.ValidationError({"object_id": "The referenced object does not exist"})
        allowed_kinds = {
            "vendor": {Document.Kind.AADHAAR, Document.Kind.PAN},
            "driver": {Document.Kind.AADHAAR, Document.Kind.PAN, Document.Kind.DRIVING_LICENSE},
            "vendor_bank_account": {Document.Kind.CANCELLED_CHEQUE},
        }
        kind = serializer.validated_data["kind"]
        sensitive_kinds = set().union(*allowed_kinds.values())
        if (
            object_type in allowed_kinds and kind not in allowed_kinds[object_type]
        ) or (
            kind in sensitive_kinds and kind not in allowed_kinds.get(object_type, set())
        ):
            raise serializers.ValidationError({"kind": "This document type is not valid for the selected record"})
        document = serializer.save(
            original_name=uploaded.name[:255],
            content_type=inspection.content_type,
            size=uploaded.size,
            sha256=inspection.sha256,
            scan_status=inspection.status,
            scan_detail=inspection.detail,
            uploaded_by=self.request.user,
        )
        if object_type == "trip" and document.kind == Document.Kind.POD:
            Trip.objects.filter(pk=object_id).update(pod_status="RECEIVED")
        if object_type == "comment":
            Comment.objects.get(pk=object_id).attachments.add(document)
        record_audit(actor=self.request.user, action="DOCUMENT_UPLOADED", instance=document, after={"kind": document.kind, "sha256": document.sha256}, request_id=getattr(self.request, "request_id", ""))

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        document = self.get_object()
        return FileResponse(document.file.open("rb"), as_attachment=True, filename=document.original_name)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """The same bytes as `download`, rendered in place for the document viewer."""
        document = self.get_object()
        inline = document.content_type in INLINE_PREVIEW_TYPES
        response = FileResponse(
            document.file.open("rb"),
            as_attachment=not inline,
            filename=document.original_name,
            content_type=document.content_type if inline else "application/octet-stream",
        )
        # Uploaded bytes served from the app origin: stop the browser sniffing a
        # different type and stop the document itself running anything. Uploads are
        # already signature-checked by core.files, so this is defence in depth.
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "sandbox; default-src 'none'; object-src 'none'"
        return response


class TripRecoveryViewSet(viewsets.ModelViewSet):
    serializer_class = TripRecoverySerializer
    permission_classes = [TripsPermission]
    queryset = TripRecovery.objects.select_related("trip", "created_by", "resolved_by").order_by("-created_at")
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == User.Role.TRANSPORTER:
            return queryset.filter(trip__vendor_id=self.request.user.vendor_id)
        return queryset

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        recovery = self.get_object()
        if not request.data.get("reference", recovery.reference).strip():
            return Response({"detail": "Resolution reference is required"}, status=400)
        recovery.reference = request.data.get("reference", recovery.reference)
        recovery.status = "RESOLVED"
        recovery.resolved_by = request.user
        recovery.resolved_at = timezone.now()
        recovery.save(update_fields=["reference", "status", "resolved_by", "resolved_at", "updated_at"])
        record_audit(actor=request.user, action="TRIP_RECOVERY_RESOLVED", instance=recovery, after={"reference": recovery.reference}, request_id=getattr(request, "request_id", ""))
        return Response(self.get_serializer(recovery).data)
