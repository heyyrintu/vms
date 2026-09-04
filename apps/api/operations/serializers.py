import re

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from accounts.permissions import has_capability
from approvals.services import calculate_trip_advance

from .models import (
    Client,
    Document,
    Driver,
    Indent,
    Trip,
    TripCharge,
    TripIndent,
    TripRecovery,
    Vehicle,
    Vendor,
    VendorBankAccount,
    VendorContact,
)


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = "__all__"


class VendorContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorContact
        fields = "__all__"


class VendorBankAccountSerializer(serializers.ModelSerializer):
    masked_account_number = serializers.CharField(read_only=True)
    account_number = serializers.CharField(write_only=True, required=False, min_length=4)
    cancelled_cheque_uploaded = serializers.SerializerMethodField()

    class Meta:
        model = VendorBankAccount
        fields = ["id", "vendor", "bank_name", "account_holder", "account_number", "masked_account_number", "ifsc_code", "cancelled_cheque_uploaded", "active", "created_at", "updated_at"]
        read_only_fields = ["id", "masked_account_number", "cancelled_cheque_uploaded", "created_at", "updated_at"]

    @extend_schema_field(serializers.BooleanField())
    def get_cancelled_cheque_uploaded(self, obj):
        return Document.objects.filter(
            object_type="vendor_bank_account",
            object_id=str(obj.pk),
            kind=Document.Kind.CANCELLED_CHEQUE,
            scan_status="CLEAN",
        ).exists()

    def validate_account_number(self, value):
        normalized = re.sub(r"[\s-]", "", value or "")
        if not normalized.isdigit() or not 6 <= len(normalized) <= 34:
            raise serializers.ValidationError("Enter a valid account number containing 6-34 digits")
        return normalized

    def validate_ifsc_code(self, value):
        normalized = (value or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", normalized):
            raise serializers.ValidationError("Enter a valid 11-character IFSC code, for example HDFC0001234")
        return normalized

    def create(self, validated_data):
        from core.crypto import encrypt_value

        account_number = validated_data.pop("account_number", "")
        if not account_number:
            raise serializers.ValidationError({"account_number": "Account number is required"})
        return VendorBankAccount.objects.create(
            account_number_encrypted=encrypt_value(account_number),
            account_last_four=account_number[-4:],
            **validated_data,
        )

    def update(self, instance, validated_data):
        from core.crypto import encrypt_value

        account_number = validated_data.pop("account_number", "")
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if account_number:
            instance.account_number_encrypted = encrypt_value(account_number)
            instance.account_last_four = account_number[-4:]
        instance.save()
        return instance


class VendorSerializer(serializers.ModelSerializer):
    vehicles_count = serializers.IntegerField(source="vehicles.count", read_only=True)
    contacts = VendorContactSerializer(many=True, read_only=True)
    bank_accounts = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = "__all__"

    @extend_schema_field(VendorBankAccountSerializer(many=True))
    def get_bank_accounts(self, obj):
        request = self.context.get("request")
        if not request or not (
            has_capability(request.user, "sensitive.read")
            or has_capability(request.user, "masters.write")
        ):
            return []
        return VendorBankAccountSerializer(obj.bank_accounts.all(), many=True).data

    def validate_primary_phone(self, value):
        normalized = re.sub(r"[\s()+-]", "", value or "")
        if normalized and (not normalized.isdigit() or not 8 <= len(normalized) <= 15 or normalized[0] == "0"):
            raise serializers.ValidationError(
                "Enter the WhatsApp number with country code using 8-15 digits, for example 919876543210"
            )
        return normalized

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if not request or not has_capability(request.user, "sensitive.read"):
            if data.get("primary_phone"):
                data["primary_phone"] = f"••••{data['primary_phone'][-4:]}"
            if data.get("tax_identifier"):
                data["tax_identifier"] = f"••••{data['tax_identifier'][-4:]}"
        return data


class VehicleSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)

    class Meta:
        model = Vehicle
        fields = "__all__"


class DriverSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)

    class Meta:
        model = Driver
        fields = "__all__"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and not has_capability(request.user, "sensitive.read") and data.get("phone"):
            data["phone"] = f"••••{data['phone'][-4:]}"
        return data


class IndentSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    trip_count = serializers.SerializerMethodField()
    trip_numbers = serializers.SerializerMethodField()
    trip_summaries = serializers.SerializerMethodField()

    class Meta:
        model = Indent
        fields = "__all__"
        extra_kwargs = {
            "indent_no": {"required": False},
            "indent_date": {"required": False},
        }

    @extend_schema_field(serializers.IntegerField())
    def get_trip_count(self, obj):
        return obj.assigned_trips.count()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_trip_numbers(self, obj):
        return list(obj.assigned_trips.order_by("-deployment_date", "-id").values_list("trip_no", flat=True))

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_trip_summaries(self, obj):
        summaries = []
        for trip in sorted(obj.assigned_trips.all(), key=lambda row: (row.deployment_date, row.pk), reverse=True):
            if trip.status == Trip.Status.ADVANCE_PARTIALLY_PAID:
                payment_state = "PARTIALLY PAID"
            elif trip.status in {
                Trip.Status.ADVANCE_PAID,
                Trip.Status.DEPLOYED,
                Trip.Status.IN_TRANSIT,
                Trip.Status.DELIVERED,
                Trip.Status.SETTLEMENT_PENDING,
                Trip.Status.SETTLEMENT_APPROVAL_PENDING,
                Trip.Status.SETTLED,
            }:
                payment_state = "PAID / TRACKED"
            elif trip.status == Trip.Status.ADVANCE_APPROVED:
                payment_state = "APPROVED / UNPAID"
            elif trip.status == Trip.Status.ADVANCE_APPROVAL_PENDING:
                payment_state = "APPROVAL PENDING"
            else:
                payment_state = "NOT REQUESTED"
            summaries.append(
                {"id": trip.pk, "trip_no": trip.trip_no, "trip_status": trip.status, "payment_state": payment_state}
            )
        return summaries

    def validate(self, attrs):
        challan_no = (
            attrs.get("challan_no")
            or attrs.get("indent_no")
            or getattr(self.instance, "challan_no", "")
            or getattr(self.instance, "indent_no", "")
        ).strip().upper()
        client = attrs.get("client", getattr(self.instance, "client", None))
        if not challan_no:
            raise serializers.ValidationError({"challan_no": "Challan number is required"})
        duplicate = Indent.objects.filter(client=client, challan_no=challan_no)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError({"challan_no": "This challan number already exists for the client"})
        attrs["challan_no"] = challan_no
        if not attrs.get("indent_no") and not self.instance:
            candidate = challan_no
            if Indent.objects.filter(indent_no=candidate).exists() and client:
                candidate = f"{client.code}-{challan_no}"[:50]
            attrs["indent_no"] = candidate
        challan_datetime = attrs.get("challan_datetime")
        if challan_datetime:
            attrs["indent_date"] = challan_datetime.date()
        if not attrs.get("indent_date") and not getattr(self.instance, "indent_date", None):
            raise serializers.ValidationError({"challan_datetime": "Challan date and time is required"})
        return attrs


class TripChargeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TripCharge
        fields = "__all__"
        read_only_fields = ["created_by"]


class DocumentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            "id",
            "object_type",
            "object_id",
            "kind",
            "file",
            "download_url",
            "original_name",
            "content_type",
            "size",
            "sha256",
            "scan_status",
            "scan_detail",
            "uploaded_by",
            "created_at",
        ]
        read_only_fields = [
            "download_url",
            "original_name",
            "content_type",
            "size",
            "sha256",
            "scan_status",
            "scan_detail",
            "uploaded_by",
            "created_at",
        ]
        extra_kwargs = {"file": {"write_only": True}}

    @extend_schema_field(serializers.URLField())
    def get_download_url(self, obj):
        request = self.context.get("request")
        path = f"/api/documents/{obj.pk}/download/"
        return request.build_absolute_uri(path) if request else path


class TripRecoverySerializer(serializers.ModelSerializer):
    trip_no = serializers.CharField(source="trip.trip_no", read_only=True)

    class Meta:
        model = TripRecovery
        fields = "__all__"
        read_only_fields = ["created_by", "resolved_by", "resolved_at", "status"]


class TripSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    indent_no = serializers.CharField(source="indent.indent_no", read_only=True)
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)
    vehicle_no = serializers.CharField(source="vehicle_registration_snapshot", read_only=True)
    driver_name = serializers.CharField(source="driver_name_snapshot", read_only=True)
    charges = TripChargeSerializer(many=True, read_only=True)
    calculation = serializers.SerializerMethodField()
    indent_ids = serializers.PrimaryKeyRelatedField(
        queryset=Indent.objects.all(), many=True, write_only=True, required=False
    )
    indent_details = serializers.SerializerMethodField()
    indent_count = serializers.SerializerMethodField()

    class Meta:
        model = Trip
        fields = "__all__"
        read_only_fields = [
            "trip_no",
            "vehicle_registration_snapshot",
            "vehicle_type_snapshot",
            "driver_name_snapshot",
            "driver_phone_snapshot",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_indent_count(self, obj):
        return obj.indent_links.count()

    @extend_schema_field(IndentSerializer(many=True))
    def get_indent_details(self, obj):
        links = sorted(
            obj.indent_links.all(),
            key=lambda link: (not link.is_primary, link.sequence, link.pk),
        )
        return IndentSerializer(
            [link.indent for link in links], many=True, context=self.context
        ).data

    def _sync_indents(self, trip, indents):
        if not indents:
            raise serializers.ValidationError({"indent_ids": "Select at least one indent"})
        TripIndent.objects.filter(trip=trip).delete()
        TripIndent.objects.bulk_create(
            [
                TripIndent(trip=trip, indent=indent, sequence=index, is_primary=index == 1)
                for index, indent in enumerate(indents, start=1)
            ]
        )
        primary = indents[0]
        if trip.indent_id != primary.pk:
            Trip.objects.filter(pk=trip.pk).update(indent=primary)
            trip.indent = primary

    def create(self, validated_data):
        indents = validated_data.pop("indent_ids", [])
        if indents and "indent" not in validated_data:
            validated_data["indent"] = indents[0]
        trip = super().create(validated_data)
        if indents:
            self._sync_indents(trip, indents)
        return trip

    def update(self, instance, validated_data):
        indents = validated_data.pop("indent_ids", None)
        if indents is not None:
            validated_data["indent"] = indents[0] if indents else instance.indent
        trip = super().update(instance, validated_data)
        if indents is not None:
            self._sync_indents(trip, indents)
        return trip

    @extend_schema_field(serializers.DictField())
    def get_calculation(self, obj):
        try:
            return calculate_trip_advance(obj).as_dict()
        except ValueError as exc:
            return {"error": str(exc)}

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and request.user.role == "TRANSPORTER":
            if data.get("driver_phone_snapshot"):
                data["driver_phone_snapshot"] = f"••••{data['driver_phone_snapshot'][-4:]}"
            data["client_billing_amount"] = None
            data["cost_center"] = ""
            data["notes"] = ""
        return data

    def validate(self, attrs):
        vendor = attrs.get("vendor", getattr(self.instance, "vendor", None))
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        driver = attrs.get("driver", getattr(self.instance, "driver", None))
        indent = attrs.get("indent", getattr(self.instance, "indent", None))
        client = attrs.get("client", getattr(self.instance, "client", None))
        indents = attrs.get("indent_ids")
        if vehicle and vendor and vehicle.vendor_id != vendor.id:
            raise serializers.ValidationError({"vehicle": "Vehicle must belong to the vendor"})
        if driver and driver.vendor_id and vendor and driver.vendor_id != vendor.id:
            raise serializers.ValidationError({"driver": "Driver must belong to the vendor"})
        if indent and client and indent.client_id != client.id:
            raise serializers.ValidationError({"indent": "Indent and trip client must match"})
        if indents is not None:
            if not indents:
                raise serializers.ValidationError({"indent_ids": "Select at least one indent"})
            if len({row.pk for row in indents}) != len(indents):
                raise serializers.ValidationError({"indent_ids": "Each indent may be selected only once"})
            wrong_client = [row.indent_no for row in indents if client and row.client_id != client.id]
            if wrong_client:
                raise serializers.ValidationError(
                    {"indent_ids": f"These indents belong to another client: {', '.join(wrong_client)}"}
                )
        return attrs
