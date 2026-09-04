from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from operations.models import Trip

from .models import (
    ClientBilling,
    FinalTripSettlement,
    FinancePaymentTransaction,
    PaymentAllocation,
    TDSEntry,
)


class PaymentAllocationSerializer(serializers.ModelSerializer):
    trip_no = serializers.CharField(source="trip.trip_no", read_only=True)
    approval_no = serializers.CharField(source="approval_item.batch.approval_no", read_only=True)

    class Meta:
        model = PaymentAllocation
        fields = "__all__"


class PaymentSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)
    allocations = PaymentAllocationSerializer(many=True, read_only=True)
    duplicate_utr_warning = serializers.SerializerMethodField()

    class Meta:
        model = FinancePaymentTransaction
        fields = "__all__"

    @extend_schema_field(serializers.BooleanField())
    def get_duplicate_utr_warning(self, obj):
        return FinancePaymentTransaction.objects.exclude(pk=obj.pk).filter(
            utr_reference__iexact=obj.utr_reference
        ).exists()


class AllocationInputSerializer(serializers.Serializer):
    approval_item_id = serializers.IntegerField(min_value=1)
    gross_amount_allocated = serializers.DecimalField(max_digits=14, decimal_places=2)
    tds_allocated = serializers.DecimalField(max_digits=14, decimal_places=2)
    net_cash_allocated = serializers.DecimalField(max_digits=14, decimal_places=2)


class PaymentCreateSerializer(serializers.Serializer):
    vendor = serializers.IntegerField(min_value=1)
    payment_date = serializers.DateField()
    bank_account = serializers.IntegerField(required=False, allow_null=True)
    payment_mode = serializers.CharField(default="BANK_TRANSFER")
    utr_reference = serializers.CharField(max_length=100)
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    proof_document = serializers.IntegerField(required=False, allow_null=True)
    allocations = AllocationInputSerializer(many=True, min_length=1)


class TDSEntrySerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)
    trip_no = serializers.CharField(source="trip.trip_no", read_only=True)
    payment_no = serializers.CharField(source="payment.payment_no", read_only=True)

    class Meta:
        model = TDSEntry
        fields = "__all__"


class FinalTripSettlementSerializer(serializers.ModelSerializer):
    trip_no = serializers.CharField(source="trip.trip_no", read_only=True)
    missing_documents = serializers.SerializerMethodField()

    class Meta:
        model = FinalTripSettlement
        fields = "__all__"
        read_only_fields = [
            "total_vendor_gross_cost",
            "total_tds_required",
            "total_tds_deducted",
            "total_net_vendor_payable",
            "total_cash_paid",
            "remaining_cash_payable",
            "settlement_approval",
            "settlement_status",
            "calculation_snapshot",
            "created_by",
            "approved_at",
            "settled_at",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_missing_documents(self, obj):
        from .services import settlement_documents_ready

        return settlement_documents_ready(obj.trip)


class ClientBillingSerializer(serializers.ModelSerializer):
    trip_no = serializers.CharField(source="trip.trip_no", read_only=True)
    gross_profit = serializers.SerializerMethodField()
    margin_percent = serializers.SerializerMethodField()

    class Meta:
        model = ClientBilling
        fields = "__all__"
        read_only_fields = ["client", "created_by"]

    def validate(self, attrs):
        trip = attrs.get("trip", getattr(self.instance, "trip", None))
        if trip and trip.status not in {Trip.Status.DELIVERED, Trip.Status.SETTLEMENT_PENDING, Trip.Status.SETTLEMENT_APPROVAL_PENDING, Trip.Status.SETTLED}:
            raise serializers.ValidationError("Trip must be delivered before client billing")
        return attrs

    def _profit(self, obj):
        from approvals.calculations import calculate_profitability

        settlement = getattr(obj.trip, "final_settlement", None)
        cost = settlement.total_vendor_gross_cost if settlement else obj.trip.vendor_freight_rate
        return calculate_profitability(
            client_billing_amount=obj.billing_amount,
            final_vendor_gross_cost=cost,
            internal_costs=obj.internal_trip_costs,
        )

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2))
    def get_gross_profit(self, obj):
        return self._profit(obj)["gross_profit"]

    @extend_schema_field(serializers.DecimalField(max_digits=9, decimal_places=2))
    def get_margin_percent(self, obj):
        return self._profit(obj)["margin_percent"]
