import hashlib
import hmac
import json
import os
import re

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import has_capability
from approvals.models import Comment
from core.crypto import encrypt_value

from .models import (
    IntegrationConnection,
    IntegrationMessage,
    NotificationPreference,
    NotificationTemplate,
    UnmappedInboundMessage,
)
from .serializers import (
    IntegrationConnectionSerializer,
    IntegrationMessageSerializer,
    NotificationPreferenceSerializer,
    NotificationTemplateSerializer,
    UnmappedInboundSerializer,
)
from .services import (
    deliver_message,
    ingest_email_reply,
    persist_whatsapp_media,
    process_whatsapp_approval_response,
)


def _require_admin(request):
    if not has_capability(request.user, "*"):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("Administrator permission is required")


class IntegrationMessageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = IntegrationMessage.objects.none()
    serializer_class = IntegrationMessageSerializer

    def get_queryset(self):
        queryset = IntegrationMessage.objects.select_related("vendor", "user").order_by("-created_at")
        if not has_capability(self.request.user, "*"):
            queryset = queryset.filter(channel="IN_APP", user=self.request.user)
        for field in ("channel", "status", "event_key", "direction"):
            value = self.request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        message = self.get_object()
        if message.channel != "IN_APP":
            return Response({"detail": "Only in-app notifications can be marked read"}, status=400)
        message.status = "READ"
        message.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(message).data)

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        _require_admin(request)
        message = self.get_object()
        if message.status not in {"FAILED", "QUEUED"}:
            return Response({"detail": "Only queued or failed messages can be retried"}, status=400)
        try:
            deliver_message(message, actor=request.user)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=502)
        return Response(self.get_serializer(message).data)


class NotificationTemplateViewSet(viewsets.ModelViewSet):
    queryset = NotificationTemplate.objects.all()
    serializer_class = NotificationTemplateSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_admin(request)


class NotificationPreferenceViewSet(viewsets.ModelViewSet):
    queryset = NotificationPreference.objects.none()
    serializer_class = NotificationPreferenceSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return NotificationPreference.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class IntegrationConnectionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = IntegrationConnection.objects.all()
    serializer_class = IntegrationConnectionSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_admin(request)

    @action(detail=False, methods=["post"], url_path="smtp/connect")
    def smtp_connect(self, request):
        host = str(request.data.get("host", "")).strip()
        username = str(request.data.get("username", "")).strip()
        password = str(request.data.get("password", ""))
        from_email = str(request.data.get("from_email", "")).strip()
        try:
            port = int(request.data.get("port", 587))
            timeout = int(request.data.get("timeout", 20))
            validate_email(from_email)
        except (TypeError, ValueError, DjangoValidationError):
            return Response({"detail": "A valid SMTP port, timeout, and sender email are required"}, status=400)
        use_tls = request.data.get("use_tls", True) in {True, "1", "true", "True"}
        use_ssl = request.data.get("use_ssl", False) in {True, "1", "true", "True"}
        if not host or not 1 <= port <= 65535 or not 1 <= timeout <= 120:
            return Response({"detail": "SMTP host, port, and a 1-120 second timeout are required"}, status=400)
        if use_tls and use_ssl:
            return Response({"detail": "Choose either STARTTLS or implicit SSL, not both"}, status=400)
        if bool(username) != bool(password):
            return Response({"detail": "SMTP username and password must be supplied together"}, status=400)
        credentials = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "from_email": from_email,
            "use_tls": use_tls,
            "use_ssl": use_ssl,
            "timeout": timeout,
        }
        connection, _ = IntegrationConnection.objects.update_or_create(
            provider=IntegrationConnection.Provider.SMTP,
            defaults={
                "status": "CONNECTED",
                "account_label": request.data.get("account_label", from_email),
                "encrypted_credentials": encrypt_value(json.dumps(credentials)),
                "configuration": {
                    "host": host,
                    "port": port,
                    "from_email": from_email,
                    "security": "SSL" if use_ssl else "STARTTLS" if use_tls else "PLAIN",
                },
                "watch_expires_at": None,
                "last_error": "",
            },
        )
        return Response(self.get_serializer(connection).data)

    @action(detail=False, methods=["post"], url_path="whatsapp/connect")
    def whatsapp_connect(self, request):
        if not request.data.get("access_token") or not request.data.get("phone_number_id"):
            return Response({"detail": "Access token and phone number ID are required"}, status=400)
        template_defaults = {
            "approval_template_name": "drona_logitech_approval_review",
            "approval_template_language": "en",
            "finance_template_name": "drona_logitech_finance_ready",
            "finance_template_language": "en",
            "operations_approval_template_name": "drona_logitech_operations_approval",
            "operations_approval_template_language": "en",
            "operations_payment_template_name": "drona_logitech_operations_payment",
            "operations_payment_template_language": "en",
            "operations_settlement_template_name": "drona_logitech_operations_settlement",
            "operations_settlement_template_language": "en",
            "login_otp_template_name": "vms_login",
            "login_otp_template_language": "en",
            "password_recovery_template_name": "password_recovery",
            "password_recovery_template_language": "en",
        }
        configuration = {
            key: str(request.data.get(key, default)).strip()
            for key, default in template_defaults.items()
        }
        for key, value in configuration.items():
            if not value:
                return Response({"detail": f"{key} is required"}, status=400)
            if key.endswith("_name") and not re.fullmatch(r"[a-z0-9_]{1,512}", value):
                return Response(
                    {"detail": f"{key} must contain only lowercase letters, numbers, and underscores"},
                    status=400,
                )
        existing = IntegrationConnection.objects.filter(
            provider=IntegrationConnection.Provider.WHATSAPP
        ).first()
        existing_configuration = (existing.configuration if existing else None) or {}
        for key in ("login_button_type", "password_reset_button_type"):
            if key in request.data:
                value = str(request.data.get(key, "none")).strip().lower()
                if value not in {"none", "copy_code", "url"}:
                    return Response({"detail": f"{key} must be none, copy_code or url"}, status=400)
                configuration[key] = value
            elif key in existing_configuration:
                # Preserve whatever is already stored so an omitted key doesn't
                # silently re-pin the setting to "none" and shadow the env default.
                configuration[key] = existing_configuration[key]
        credentials = {
            "access_token": request.data["access_token"],
            "phone_number_id": request.data["phone_number_id"],
        }
        connection, _ = IntegrationConnection.objects.update_or_create(
            provider=IntegrationConnection.Provider.WHATSAPP,
            defaults={
                "status": "CONNECTED",
                "account_label": request.data.get("account_label", request.data["phone_number_id"]),
                "encrypted_credentials": encrypt_value(json.dumps(credentials)),
                "configuration": configuration,
                "last_error": "",
            },
        )
        return Response(self.get_serializer(connection).data)

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        connection = self.get_object()
        connection.status = "DISCONNECTED"
        connection.encrypted_credentials = ""
        connection.watch_expires_at = None
        connection.save(
            update_fields=["status", "encrypted_credentials", "watch_expires_at", "updated_at"]
        )
        return Response(self.get_serializer(connection).data)

class UnmappedInboundViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = UnmappedInboundMessage.objects.select_related("message", "resolved_by").order_by("-created_at")
    serializer_class = UnmappedInboundSerializer

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _require_admin(request)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        item = self.get_object()
        object_type = request.data.get("object_type", "")
        object_id = str(request.data.get("object_id", ""))
        if object_type not in {"approval", "trip", "payment"} or not object_id:
            return Response({"detail": "A valid object type and ID are required"}, status=400)
        from approvals.models import PaymentApprovalBatch
        from operations.models import Trip
        from payments.models import FinancePaymentTransaction

        model = {"approval": PaymentApprovalBatch, "trip": Trip, "payment": FinancePaymentTransaction}[object_type]
        try:
            target_pk = int(object_id)
        except ValueError:
            return Response({"detail": "Object id must be a whole number"}, status=400)
        if not model.objects.filter(pk=target_pk).exists():
            return Response({"detail": f"No {object_type} with id {object_id} exists"}, status=400)
        item.message.object_type = object_type
        item.message.object_id = object_id
        item.message.save(update_fields=["object_type", "object_id", "updated_at"])
        if object_type in {"approval", "trip", "payment"}:
            Comment.objects.create(
                object_type=object_type,
                object_id=object_id,
                author=request.user,
                body=f"Reconciled inbound {item.message.channel} message:\n\n{item.message.body_summary}",
            )
        item.resolved_by = request.user
        item.resolved_at = timezone.now()
        item.save(update_fields=["resolved_by", "resolved_at", "updated_at"])
        return Response(self.get_serializer(item).data)


class EmailWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "webhook"

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        verification = os.getenv("EMAIL_WEBHOOK_TOKEN", "")
        if verification and not hmac.compare_digest(
            request.headers.get("Authorization", ""), f"Bearer {verification}"
        ):
            return Response({"detail": "Invalid email webhook authorization"}, status=403)
        required = ["external_message_id", "external_thread_id", "subject", "body"]
        if any(key not in request.data for key in required):
            return Response({"detail": "Malformed inbound email event"}, status=400)
        message = ingest_email_reply(
            external_message_id=request.data["external_message_id"],
            external_thread_id=request.data["external_thread_id"],
            subject=request.data["subject"],
            body=request.data["body"],
            sender=request.data.get("sender", ""),
        )
        return Response({"status": "processed", "message_id": message.pk})


class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "webhook"

    @extend_schema(request=None, responses=dict)
    def get(self, request):
        if request.query_params.get("hub.verify_token") != os.getenv(
            "WHATSAPP_VERIFY_TOKEN", "local-verify-token"
        ):
            return Response({"detail": "Invalid verification token"}, status=403)
        return Response(int(request.query_params.get("hub.challenge", "0")))

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
        if app_secret:
            signature = request.headers.get("X-Hub-Signature-256", "").removeprefix("sha256=")
            expected = hmac.new(app_secret.encode(), request.body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return Response({"detail": "Invalid webhook signature"}, status=403)
        if "entry" in request.data:
            return self._process_cloud_payload(request.data)
        event_id = str(request.data.get("event_id", ""))
        if not event_id:
            return Response({"detail": "event_id is required"}, status=400)
        message, created = IntegrationMessage.objects.get_or_create(
            idempotency_key=f"whatsapp-inbound:{event_id}",
            defaults={
                "channel": IntegrationMessage.Channel.WHATSAPP,
                "direction": "INBOUND",
                "external_message_id": str(request.data.get("message_id", "")),
                "object_type": str(request.data.get("object_type", "unmapped")),
                "object_id": str(request.data.get("object_id", "")),
                "body_summary": str(request.data.get("body", ""))[:1000],
                "status": str(request.data.get("status", "RECEIVED")).upper(),
            },
        )
        return Response({"status": "processed" if created else "duplicate", "message_id": message.pk})

    def _process_cloud_payload(self, payload):
        processed = 0
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for status_event in value.get("statuses", []):
                    message = IntegrationMessage.objects.filter(
                        channel=IntegrationMessage.Channel.WHATSAPP,
                        external_message_id=status_event.get("id", ""),
                        direction="OUTBOUND",
                    ).first()
                    if message:
                        message.status = status_event.get("status", "").upper()
                        message.raw_metadata = status_event
                        message.save(update_fields=["status", "raw_metadata", "updated_at"])
                        processed += 1
                for inbound in value.get("messages", []):
                    message_id = inbound.get("id", "")
                    context_id = inbound.get("context", {}).get("id", "")
                    outbound = (
                        IntegrationMessage.objects.filter(
                            channel=IntegrationMessage.Channel.WHATSAPP, external_message_id=context_id, direction="OUTBOUND"
                        ).first()
                        if context_id
                        else None
                    )
                    button_payload = (
                        inbound.get("button", {}).get("payload", "")
                        or inbound.get("interactive", {}).get("button_reply", {}).get("id", "")
                    )
                    body = (
                        inbound.get("text", {}).get("body", "")
                        or inbound.get("button", {}).get("text", "")
                        or inbound.get("interactive", {}).get("button_reply", {}).get("title", "")
                    )
                    media = next(
                        (inbound.get(kind) for kind in ("document", "image", "audio", "video") if inbound.get(kind)),
                        None,
                    )
                    message, created = IntegrationMessage.objects.get_or_create(
                        idempotency_key=f"whatsapp-inbound:{message_id}",
                        defaults={
                            "channel": "WHATSAPP",
                            "direction": "INBOUND",
                            "external_message_id": message_id,
                            "external_thread_id": inbound.get("from", ""),
                            "object_type": outbound.object_type if outbound else "unmapped",
                            "object_id": outbound.object_id if outbound else "",
                            "vendor": outbound.vendor if outbound else None,
                            "recipient": inbound.get("from", ""),
                            "body_summary": body[:1000] or "Inbound media",
                            "raw_metadata": {"type": inbound.get("type"), "media": media or {}},
                            "status": "RECEIVED",
                            "received_at": timezone.now(),
                        },
                    )
                    if created and not outbound:
                        UnmappedInboundMessage.objects.create(
                            message=message, reason="No replied-to provider message was found"
                        )
                    if created and media:
                        try:
                            persist_whatsapp_media(message, media)
                        except (KeyError, RuntimeError, ValueError) as exc:
                            message.raw_metadata = {
                                **message.raw_metadata,
                                "media_error": str(exc)[:500],
                            }
                            message.save(update_fields=["raw_metadata", "updated_at"])
                    if created and button_payload:
                        try:
                            process_whatsapp_approval_response(
                                inbound_message=message,
                                outbound_message=outbound,
                                sender=inbound.get("from", ""),
                                payload=button_payload,
                            )
                        except (PermissionError, ValueError) as exc:
                            message.raw_metadata = {
                                **message.raw_metadata,
                                "approval_error": str(exc)[:500],
                                "decision_status": "REJECTED",
                            }
                            message.save(update_fields=["raw_metadata", "updated_at"])
                    processed += int(created)
        return Response({"status": "processed", "events": processed})
