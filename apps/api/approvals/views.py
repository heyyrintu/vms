from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import User
from accounts.permissions import RolePermission, has_capability
from audit.models import record_audit

from .models import ApprovalRule, Comment, PaymentApprovalBatch
from .serializers import (
    ApprovalBatchCreateSerializer,
    ApprovalBatchSerializer,
    ApprovalRuleSerializer,
    CommentSerializer,
    DecisionSerializer,
)
from .services import decide_batch, submit_batch


class ApprovalPermission(RolePermission):
    read_capability = "approvals.read"
    write_capability = "approvals.request"

    def has_permission(self, request, view):
        if getattr(view, "action", "") in {"decide"}:
            return bool(request.user and request.user.is_authenticated)
        if getattr(view, "action", "") in {"comments"} and request.method == "POST":
            return has_capability(request.user, "comments.write")
        return super().has_permission(request, view)


class ApprovalBatchViewSet(viewsets.ModelViewSet):
    permission_classes = [ApprovalPermission]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = PaymentApprovalBatch.objects.select_related("client", "requested_by").prefetch_related("items__trip", "items__vendor", "actions__actor").order_by("-created_at")
        if getattr(self.request.user, "role", "") == User.Role.OPERATIONS:
            queryset = queryset.filter(requested_by=self.request.user)
        if getattr(self.request.user, "role", "") == User.Role.TRANSPORTER:
            queryset = queryset.filter(items__vendor_id=self.request.user.vendor_id).distinct()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(approval_no__icontains=search)
                | Q(requested_by__username__icontains=search)
                | Q(requested_by__first_name__icontains=search)
                | Q(requested_by__last_name__icontains=search)
                | Q(client__name__icontains=search)
                | Q(items__trip__trip_no__icontains=search)
                | Q(items__vendor__display_name__icontains=search)
            )
        requester = self.request.query_params.get("requester")
        client = self.request.query_params.get("client")
        if requester:
            queryset = queryset.filter(requested_by_id=requester)
        if client:
            queryset = queryset.filter(client_id=client)
        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset.distinct()

    def get_serializer_class(self):
        return ApprovalBatchCreateSerializer if self.action == "create" else ApprovalBatchSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = serializer.save()
        if serializer.validated_data.get("submit"):
            batch = submit_batch(batch=batch, actor=request.user, request_id=getattr(request, "request_id", ""))
        return Response(ApprovalBatchSerializer(batch, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        batch = submit_batch(batch=self.get_object(), actor=request.user, request_id=getattr(request, "request_id", ""))
        return Response(ApprovalBatchSerializer(batch, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        serializer = DecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        batch = decide_batch(
            batch=self.get_object(),
            actor=request.user,
            request_id=getattr(request, "request_id", ""),
            **serializer.validated_data,
        )
        return Response(ApprovalBatchSerializer(batch, context={"request": request}).data)

    @action(detail=True, methods=["get", "post"])
    def comments(self, request, pk=None):
        batch = self.get_object()
        queryset = Comment.objects.filter(object_type="approval", object_id=str(batch.pk)).select_related("author")
        if request.user.role == User.Role.TRANSPORTER:
            queryset = queryset.none()
        if request.method == "GET":
            return Response(CommentSerializer(queryset, many=True).data)
        serializer = CommentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = serializer.save(author=request.user, object_type="approval", object_id=str(batch.pk))
        from integrations.services import emit_mention_events

        emit_mention_events(comment)
        record_audit(actor=request.user, action="COMMENT_ADDED", instance=batch, after={"comment_id": comment.pk, "visibility": comment.visibility}, request_id=getattr(request, "request_id", ""))
        return Response(CommentSerializer(comment).data, status=201)


class ApprovalRuleViewSet(viewsets.ModelViewSet):
    serializer_class = ApprovalRuleSerializer
    queryset = ApprovalRule.objects.prefetch_related("stages").all()

    def get_permissions(self):
        return [ApprovalPermission()]

    def perform_create(self, serializer):
        if not has_capability(self.request.user, "*"):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Administrator permission is required")
        serializer.save()

    def perform_update(self, serializer):
        self.perform_create(serializer)

    def perform_destroy(self, instance):
        if not has_capability(self.request.user, "*"):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Administrator permission is required")
        instance.delete()


class CommentPermission(ApprovalPermission):
    def has_permission(self, request, view):
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return has_capability(request.user, "approvals.read") or has_capability(
                request.user, "trips.read"
            )
        return has_capability(request.user, "comments.write") or has_capability(request.user, "*")


class CommentViewSet(viewsets.ModelViewSet):
    queryset = Comment.objects.none()
    serializer_class = CommentSerializer
    permission_classes = [CommentPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = Comment.objects.select_related("author").prefetch_related("mentions", "attachments")
        if self.request.user.role == User.Role.TRANSPORTER:
            from operations.models import Trip
            from payments.models import FinancePaymentTransaction

            vendor_id = self.request.user.vendor_id
            trip_ids = [str(value) for value in Trip.objects.filter(vendor_id=vendor_id).values_list("id", flat=True)]
            payment_ids = [
                str(value)
                for value in FinancePaymentTransaction.objects.filter(vendor_id=vendor_id).values_list(
                    "id", flat=True
                )
            ]
            from django.db.models import Q

            queryset = queryset.filter(visibility=Comment.Visibility.TRANSPORTER_VISIBLE).filter(
                Q(object_type="trip", object_id__in=trip_ids)
                | Q(object_type="payment", object_id__in=payment_ids)
            )
        for field in ("object_type", "object_id"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset.order_by("created_at", "id")

    @action(detail=False, methods=["get"], url_path="mention-candidates")
    def mention_candidates(self, request):
        users = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        return Response(
            [
                {
                    "id": user.pk,
                    "label": user.get_full_name() or user.username,
                    "role": user.role,
                }
                for user in users
            ]
        )

    def perform_create(self, serializer):
        if not has_capability(self.request.user, "comments.write"):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Comment permission is required")
        object_type = serializer.validated_data.get("object_type")
        if object_type not in {"approval", "trip", "payment"}:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"object_type": "Comments require an approval, trip, or payment context"})
        from operations.models import Trip
        from payments.models import FinancePaymentTransaction

        context_model = {
            "approval": PaymentApprovalBatch,
            "trip": Trip,
            "payment": FinancePaymentTransaction,
        }[object_type]
        if not context_model.objects.filter(pk=serializer.validated_data.get("object_id")).exists():
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"object_id": "The referenced object does not exist"})
        comment = serializer.save(author=self.request.user)
        from integrations.services import emit_mention_events

        emit_mention_events(comment)
        record_audit(actor=self.request.user, action="COMMENT_ADDED", instance=comment, after={"object_type": comment.object_type, "object_id": comment.object_id}, request_id=getattr(self.request, "request_id", ""))

    def perform_update(self, serializer):
        comment = serializer.instance
        from rest_framework.exceptions import PermissionDenied

        from core.models import OrganizationSettings

        deadline = comment.created_at + timedelta(
            minutes=OrganizationSettings.load().comment_edit_window_minutes
        )
        if comment.author_id != self.request.user.pk and not has_capability(self.request.user, "*"):
            raise PermissionDenied("Only the author can edit this comment")
        if timezone.now() > deadline and not has_capability(self.request.user, "*"):
            raise PermissionDenied("The comment edit window has expired")
        old_body = comment.body
        history = [*comment.edit_history, {"body": old_body, "edited_at": timezone.now().isoformat()}]
        updated = serializer.save(edit_history=history, edited_at=timezone.now())
        record_audit(actor=self.request.user, action="COMMENT_EDITED", instance=updated, before={"body": old_body}, after={"body": updated.body}, request_id=getattr(self.request, "request_id", ""))
