from django.db import connection
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_capability

from .models import OrganizationSettings
from .serializers import OrganizationSettingsSerializer


class HealthView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"status": "ok", "service": "vms-api"})


class ReadinessView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=dict)
    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return Response({"status": "ready", "database": "ok"})


class SettingsView(APIView):
    @extend_schema(responses=OrganizationSettingsSerializer)
    def get(self, request):
        return Response(OrganizationSettingsSerializer(OrganizationSettings.load()).data)

    @extend_schema(request=OrganizationSettingsSerializer, responses=OrganizationSettingsSerializer)
    def patch(self, request):
        if not has_capability(request.user, "*"):
            return Response({"detail": "Administrator permission is required"}, status=403)
        settings = OrganizationSettings.load()
        serializer = OrganizationSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PermissionMatrixView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        from accounts.permissions import ROLE_CAPABILITIES

        return Response({role: sorted(capabilities) for role, capabilities in ROLE_CAPABILITIES.items()})


class GlobalSearchView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        term = request.query_params.get("q", "").strip()
        if len(term) < 2:
            return Response({"results": []})
        from approvals.models import PaymentApprovalBatch
        from operations.models import Driver, Trip, Vendor
        from payments.models import FinancePaymentTransaction

        results = []
        transporter = request.user.role == "TRANSPORTER"
        trip_scope = {"vendor_id": request.user.vendor_id} if transporter else {}
        vendor_scope = {"pk": request.user.vendor_id} if transporter else {}
        for trip in Trip.objects.filter(**trip_scope).filter(
            Q(trip_no__icontains=term)
            | Q(indent__indent_no__icontains=term)
            | Q(indents__challan_no__icontains=term)
            | Q(indents__ship_to_party_name__icontains=term)
            | Q(vehicle_registration_snapshot__icontains=term)
            | Q(origin__icontains=term)
            | Q(destination__icontains=term)
        ).select_related("vendor").distinct()[:10]:
            results.append({"type": "trip", "id": trip.pk, "label": trip.trip_no, "detail": f"{trip.origin} → {trip.destination}"})
        for vendor in Vendor.objects.filter(**vendor_scope).filter(Q(display_name__icontains=term) | Q(vendor_code__icontains=term))[:10]:
            results.append({"type": "vendor", "id": vendor.pk, "label": vendor.display_name, "detail": vendor.vendor_code})
        approvals = PaymentApprovalBatch.objects.filter(approval_no__icontains=term)
        if request.user.role == "TRANSPORTER":
            approvals = approvals.filter(items__vendor_id=request.user.vendor_id).distinct()
        for approval in approvals[:10]:
            results.append({"type": "approval", "id": approval.pk, "label": approval.approval_no, "detail": approval.status})
        for payment in FinancePaymentTransaction.objects.filter(Q(payment_no__icontains=term) | Q(utr_reference__icontains=term)).select_related("vendor")[:10]:
            if request.user.role != "TRANSPORTER" or payment.vendor_id == request.user.vendor_id:
                results.append({"type": "payment", "id": payment.pk, "label": payment.payment_no, "detail": payment.utr_reference})
        if has_capability(request.user, "sensitive.read"):
            for driver in Driver.objects.filter(Q(name__icontains=term) | Q(phone__icontains=term))[:10]:
                results.append({"type": "driver", "id": driver.pk, "label": driver.name, "detail": driver.phone})
        return Response({"results": results[:30]})


class ChoicesView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        from operations.models import Document, Trip
        from payments.models import ClientBilling, FinancePaymentTransaction

        def rows(choices):
            return [{"value": value, "label": label} for value, label in choices]

        return Response(
            {
                "trip_status": rows(Trip.Status.choices),
                "document_kind": rows(Document.Kind.choices),
                "billing_status": rows(ClientBilling.Status.choices),
                "payment_status": rows(FinancePaymentTransaction.Status.choices),
            }
        )
