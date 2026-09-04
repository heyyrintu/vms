from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    ApprovalAction,
    ApprovalRule,
    ApprovalStage,
    ApprovalStageDecision,
    Comment,
    PaymentApprovalBatch,
    PaymentApprovalItem,
)
from .services import create_approval_batch


class ApprovalItemSerializer(serializers.ModelSerializer):
    trip_no = serializers.CharField(source="trip.trip_no", read_only=True)
    route = serializers.SerializerMethodField()
    vendor_name = serializers.CharField(source="vendor.display_name", read_only=True)
    paid_gross = serializers.SerializerMethodField()
    paid_tds = serializers.SerializerMethodField()
    paid_net = serializers.SerializerMethodField()

    class Meta:
        model = PaymentApprovalItem
        fields = "__all__"

    @extend_schema_field(serializers.CharField())
    def get_route(self, obj):
        return f"{obj.trip.origin} → {obj.trip.destination}"

    def _paid(self, obj, key):
        from payments.services import paid_totals

        return paid_totals(obj)[key]

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2))
    def get_paid_gross(self, obj):
        return self._paid(obj, "gross")

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2))
    def get_paid_tds(self, obj):
        return self._paid(obj, "tds")

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2))
    def get_paid_net(self, obj):
        return self._paid(obj, "net")


class ApprovalActionSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.get_full_name", read_only=True)

    class Meta:
        model = ApprovalAction
        fields = "__all__"


class CommentSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "object_type", "object_id", "author", "author_name", "body", "visibility", "parent", "mentions", "attachments", "edit_history", "edited_at", "created_at", "updated_at"]
        read_only_fields = ["author", "edit_history", "edited_at", "created_at", "updated_at"]

    @extend_schema_field(serializers.CharField())
    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_attachments(self, obj):
        request = self.context.get("request")
        return [
            {
                "id": document.pk,
                "kind": document.kind,
                "original_name": document.original_name,
                "scan_status": document.scan_status,
                "created_at": document.created_at,
                "download_url": request.build_absolute_uri(f"/api/documents/{document.pk}/download/") if request else f"/api/documents/{document.pk}/download/",
            }
            for document in obj.attachments.all()
        ]


class ApprovalBatchSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()
    client_name = serializers.CharField(source="client.name", read_only=True)
    items = serializers.SerializerMethodField()
    actions = ApprovalActionSerializer(many=True, read_only=True)
    vendor_subtotals = serializers.SerializerMethodField()
    stage_decisions = serializers.SerializerMethodField()

    class Meta:
        model = PaymentApprovalBatch
        fields = "__all__"
        read_only_fields = ["approval_no", "requested_by", "status", "revision_no", "submitted_at", "gross_requested", "tds_requested", "net_requested", "approval_rule_snapshot"]

    @extend_schema_field(serializers.CharField())
    def get_requester_name(self, obj):
        return obj.requested_by.get_full_name() or obj.requested_by.username

    def _visible_items(self, obj):
        queryset = obj.items.exclude(item_status=PaymentApprovalItem.Status.SUPERSEDED).select_related(
            "trip", "vendor"
        )
        request = self.context.get("request")
        if request and request.user.role == "TRANSPORTER":
            queryset = queryset.filter(vendor_id=request.user.vendor_id)
        return queryset

    @extend_schema_field(ApprovalItemSerializer(many=True))
    def get_items(self, obj):
        return ApprovalItemSerializer(self._visible_items(obj), many=True, context=self.context).data

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_vendor_subtotals(self, obj):
        groups = {}
        for item in self._visible_items(obj):
            group = groups.setdefault(item.vendor_id, {"vendor_id": item.vendor_id, "vendor_name": item.vendor.display_name, "gross": 0, "tds": 0, "net": 0})
            group["gross"] += item.gross_requested
            group["tds"] += item.tds_this_request
            group["net"] += item.net_requested
        return list(groups.values())

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_stage_decisions(self, obj):
        return ApprovalStageDecisionSerializer(obj.stage_decisions.all(), many=True).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if request and request.user.role == "TRANSPORTER":
            visible_items = list(self._visible_items(instance))
            data["gross_requested"] = format(
                sum((item.gross_requested for item in visible_items), start=0), ".2f"
            )
            data["tds_requested"] = format(
                sum((item.tds_this_request for item in visible_items), start=0), ".2f"
            )
            data["net_requested"] = format(
                sum((item.net_requested for item in visible_items), start=0), ".2f"
            )
            data["actions"] = []
            data["approval_rule_snapshot"] = {}
            visible_trip_ids = {item.trip_id for item in visible_items}
            data["revision_diff"] = [
                change
                for change in data.get("revision_diff", [])
                if change.get("trip_id") in visible_trip_ids
            ]
            for stage in data.get("stage_decisions", []):
                stage["comment"] = ""
                stage["decided_by_name"] = ""
        return data


class ApprovalBatchCreateSerializer(serializers.Serializer):
    trip_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1)
    purpose = serializers.ChoiceField(choices=["ADVANCE", "FINAL_SETTLEMENT", "OTHER"], default="ADVANCE")

    def create(self, validated_data):
        request = self.context["request"]
        return create_approval_batch(
            actor=request.user,
            trips=validated_data["trip_ids"],
            purpose=validated_data["purpose"],
            request_id=getattr(request, "request_id", ""),
        )


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["APPROVE", "REJECT", "SEND_BACK"])
    item_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class ApprovalStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalStage
        fields = ["id", "sequence", "role", "label"]


class ApprovalRuleSerializer(serializers.ModelSerializer):
    stages = ApprovalStageSerializer(many=True)

    class Meta:
        model = ApprovalRule
        fields = "__all__"

    def create(self, validated_data):
        stages = validated_data.pop("stages", [])
        rule = ApprovalRule.objects.create(**validated_data)
        for stage in stages:
            ApprovalStage.objects.create(rule=rule, **stage)
        return rule

    def update(self, instance, validated_data):
        stages = validated_data.pop("stages", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if stages is not None:
            instance.stages.all().delete()
            for stage in stages:
                ApprovalStage.objects.create(rule=instance, **stage)
        return instance


class ApprovalStageDecisionSerializer(serializers.ModelSerializer):
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalStageDecision
        fields = "__all__"

    def get_decided_by_name(self, obj):
        if not obj.decided_by:
            return ""
        return obj.decided_by.get_full_name() or obj.decided_by.username
