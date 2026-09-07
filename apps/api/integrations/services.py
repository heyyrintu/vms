import json
import mimetypes
import os
import re
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from audit.models import record_audit
from core.crypto import decrypt_value, encrypt_value

from .models import (
    IntegrationConnection,
    IntegrationMessage,
    NotificationPreference,
    NotificationTemplate,
    UnmappedInboundMessage,
)
from .providers import (
    FakeMessageProvider,
    SMTPProvider,
    WhatsAppProvider,
    download_binary,
    request_json,
)

DEFAULT_TEMPLATES = {
    "APPROVAL_REQUESTED": (
        "Approval requested",
        "Approval {reference} is waiting for your decision. Net payable: {net}. Review securely: {action_url}",
    ),
    "APPROVAL_COMPLETED": (
        "Approval completed",
        "Approval {reference} has been approved by {actor}. Review securely: {action_url}",
    ),
    "APPROVAL_REJECTED": (
        "Approval rejected",
        "Approval {reference} has been rejected by {actor}. Review securely: {action_url}",
    ),
    "CHANGES_REQUESTED": (
        "Changes requested",
        "Approval {reference} was returned for changes by {actor}. Review securely: {action_url}",
    ),
    "MENTION": ("You were mentioned", "{actor} mentioned you in {reference}."),
    "FINANCE_READY": (
        "Payment ready",
        "Approved payable {reference} is ready for finance. Net payable: {net}. Open securely: {action_url}",
    ),
    "PAYMENT_COMPLETED": (
        "Payment completed",
        "Payment {reference} has been recorded. Net paid: {net}. UTR: {utr}. Review securely: {action_url}",
    ),
    "PAYMENT_FAILED": ("Payment message failed", "A payment notification for {reference} failed."),
    "SETTLEMENT_PENDING": (
        "Settlement pending",
        "Trip {reference} is ready for final settlement. Review securely: {action_url}",
    ),
}


def _connection(provider):
    return IntegrationConnection.objects.filter(provider=provider, status="CONNECTED").first()


def _connection_credentials(connection):
    if not connection or not connection.encrypted_credentials:
        return {}
    return json.loads(decrypt_value(connection.encrypted_credentials))


def get_provider(channel):
    if channel == IntegrationMessage.Channel.EMAIL:
        connection = _connection(IntegrationConnection.Provider.SMTP)
        mode = os.getenv("EMAIL_PROVIDER", "").lower()
        if mode == "fake" or (not mode and not connection):
            return FakeMessageProvider("EMAIL")
        if mode not in {"", "smtp"}:
            raise RuntimeError("EMAIL_PROVIDER must be either fake or smtp")
        credentials = _connection_credentials(connection)
        return SMTPProvider(
            host=credentials.get("host") or os.getenv("SMTP_HOST", ""),
            port=credentials.get("port") or os.getenv("SMTP_PORT", "587"),
            username=credentials.get("username") or os.getenv("SMTP_USERNAME", ""),
            password=credentials.get("password") or os.getenv("SMTP_PASSWORD", ""),
            from_email=credentials.get("from_email") or os.getenv("SMTP_FROM_EMAIL", ""),
            use_tls=credentials.get(
                "use_tls", os.getenv("SMTP_USE_TLS", "true").lower() == "true"
            ),
            use_ssl=credentials.get(
                "use_ssl", os.getenv("SMTP_USE_SSL", "false").lower() == "true"
            ),
            timeout=credentials.get("timeout") or os.getenv("SMTP_TIMEOUT_SECONDS", "20"),
        )
    if channel == IntegrationMessage.Channel.WHATSAPP:
        connection = _connection(IntegrationConnection.Provider.WHATSAPP)
        mode = os.getenv("WHATSAPP_PROVIDER", "").lower()
        if mode == "fake" or (not mode and not connection):
            return FakeMessageProvider("WHATSAPP")
        if mode not in {"", "whatsapp"}:
            raise RuntimeError("WHATSAPP_PROVIDER must be either fake or whatsapp")
        credentials = _connection_credentials(connection)
        return WhatsAppProvider(
            access_token=credentials.get("access_token") or os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=credentials.get("phone_number_id") or os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            api_version=os.getenv("WHATSAPP_API_VERSION", "v23.0"),
        )
    return FakeMessageProvider("IN_APP")


@transaction.atomic
def queue_message(
    *,
    channel,
    recipient,
    subject,
    body,
    object_type,
    object_id,
    idempotency_key,
    vendor=None,
    user=None,
    event_key="",
    actor=None,
    provider_options=None,
    summary=None,
):
    message, created = IntegrationMessage.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "channel": channel,
            "direction": "OUTBOUND",
            "recipient": recipient,
            "subject": subject[:240],
            "body_summary": (summary if summary is not None else body)[:1000],
            "payload_encrypted": encrypt_value(json.dumps({
                "subject": subject,
                "body": body,
                "provider_options": provider_options or {},
            })),
            "object_type": object_type,
            "object_id": str(object_id),
            "vendor": vendor,
            "user": user,
            "event_key": event_key,
            "status": "DELIVERED" if channel == IntegrationMessage.Channel.IN_APP else "QUEUED",
            "sent_at": timezone.now() if channel == IntegrationMessage.Channel.IN_APP else None,
        },
    )
    if (
        created
        and channel in {IntegrationMessage.Channel.EMAIL, IntegrationMessage.Channel.WHATSAPP}
        and settings.INTEGRATION_DELIVERY_MODE == "sync"
    ):
        # Local installations often run Django without Redis/Celery. Deliver only
        # after the surrounding business transaction commits so a provider call
        # can never announce an approval/payment that was rolled back.
        transaction.on_commit(
            lambda message_id=message.pk, audit_actor=actor: deliver_message(
                message_id, actor=audit_actor
            ),
            robust=True,
        )
    elif created and channel in {IntegrationMessage.Channel.EMAIL, IntegrationMessage.Channel.WHATSAPP}:
        from .tasks import deliver_message_task

        # Dispatch immediately instead of waiting for the periodic outbox sweep.
        actor_id = getattr(actor, "pk", None) if getattr(actor, "is_authenticated", False) else None
        transaction.on_commit(
            lambda message_id=message.pk, actor_id=actor_id: deliver_message_task.delay(message_id, actor_id),
            robust=True,
        )
    return message


@transaction.atomic
def deliver_message(message_or_id, *, actor=None):
    message_id = message_or_id.pk if hasattr(message_or_id, "pk") else message_or_id
    message = IntegrationMessage.objects.select_for_update().get(pk=message_id)
    if message.status in {"SENT", "DELIVERED", "READ", "RECEIVED"}:
        return message
    payload = json.loads(decrypt_value(message.payload_encrypted))
    try:
        provider_options = dict(payload.get("provider_options") or {})
        if (
            message.channel == IntegrationMessage.Channel.WHATSAPP
            and message.event_key == "APPROVAL_REQUESTED"
            and message.user_id
        ):
            from approvals.models import PaymentApprovalBatch
            from approvals.packet import ensure_approval_packet

            batch = PaymentApprovalBatch.objects.get(pk=message.object_id)
            packet = ensure_approval_packet(batch, batch.requested_by)
            provider_options = approval_whatsapp_options(batch, message.user, packet)
        document_id = provider_options.pop("document_id", None)
        if message.channel == IntegrationMessage.Channel.WHATSAPP and document_id:
            from operations.models import Document

            document = Document.objects.get(pk=document_id, scan_status="CLEAN")
            with document.file.open("rb") as attachment:
                provider_options["document"] = {
                    "filename": document.original_name,
                    "content_type": document.content_type,
                    "content": attachment.read(),
                }
        result = get_provider(message.channel).send(
            recipient=message.recipient,
            subject=payload["subject"],
            body=payload["body"],
            idempotency_key=message.idempotency_key,
            options=provider_options,
        )
    except Exception as exc:
        message.status = "FAILED"
        message.retry_count += 1
        message.last_error = str(exc)[:2000]
        message.next_retry_at = timezone.now() + timedelta(minutes=min(60, 2**message.retry_count))
        message.save(update_fields=["status", "retry_count", "last_error", "next_retry_at", "updated_at"])
        raise
    message.external_message_id = result.message_id
    message.external_thread_id = result.thread_id
    message.status = result.status
    message.raw_metadata = result.metadata or {}
    message.sent_at = timezone.now()
    message.last_error = ""
    message.next_retry_at = None
    message.save(
        update_fields=[
            "external_message_id",
            "external_thread_id",
            "status",
            "raw_metadata",
            "sent_at",
            "last_error",
            "next_retry_at",
            "updated_at",
        ]
    )
    record_audit(actor=actor, action=f"{message.channel}_MESSAGE_SENT", instance=message, after={"status": message.status})
    return message


def send_message(**kwargs):
    actor = kwargs.pop("actor", None)
    return deliver_message(queue_message(**kwargs, actor=actor), actor=actor)


class _SafeTemplateContext(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_event(event_key, context, *, channel="IN_APP", fallback_subject=None, fallback_body=None):
    default_subject, default_body = DEFAULT_TEMPLATES.get(
        event_key, (event_key.replace("_", " ").title(), "{reference}")
    )
    default_subject = fallback_subject or default_subject
    default_body = fallback_body or default_body
    template = NotificationTemplate.objects.filter(
        event_key=event_key, channel=channel, enabled=True
    ).first()
    subject = template.subject_template if template else default_subject
    body = template.body_template if template else default_body
    safe = _SafeTemplateContext({key: str(value) for key, value in context.items()})
    return subject.format_map(safe), body.format_map(safe)


WHATSAPP_APPROVAL_SALT = "drona-logitech-whatsapp-approval-v1"


def _approval_button_token(batch, user, decision):
    decision_code = {"APPROVE": "A", "REJECT": "R"}[decision]
    value = f"{batch.pk}.{user.pk}.{decision_code}"
    return signing.TimestampSigner(salt=WHATSAPP_APPROVAL_SALT).sign(value)


def approval_whatsapp_options(batch, user, document):
    return {
        "template_name": _whatsapp_template_setting(
            "approval_template_name",
            "WHATSAPP_APPROVAL_TEMPLATE_NAME",
            "drona_logitech_approval_review",
        ),
        "template_language": _whatsapp_template_setting(
            "approval_template_language",
            "WHATSAPP_APPROVAL_TEMPLATE_LANGUAGE",
            "en",
        ),
        "document_id": document.pk,
        "body_parameters": [
            batch.approval_no,
            batch.requested_by.get_full_name() or batch.requested_by.username,
            str(batch.items.count()),
            str(batch.gross_requested),
            str(batch.tds_requested),
            str(batch.net_requested),
        ],
        "quick_reply_payloads": [
            _approval_button_token(batch, user, "APPROVE"),
            _approval_button_token(batch, user, "REJECT"),
        ],
    }


def _whatsapp_template_setting(configuration_key, environment_key, default):
    connection = _connection(IntegrationConnection.Provider.WHATSAPP)
    configuration = connection.configuration if connection else {}
    return str(
        (configuration or {}).get(configuration_key)
        or os.getenv(environment_key, default)
    ).strip()


def _user_display_name(user):
    if not user:
        return "System"
    return user.get_full_name() or user.username


def workflow_whatsapp_options(event_key, instance, *, actor=None):
    """Return the exact Meta template parameters for an internal workflow event."""
    if event_key == "FINANCE_READY":
        return {
            "template_name": _whatsapp_template_setting(
                "finance_template_name",
                "WHATSAPP_FINANCE_TEMPLATE_NAME",
                "drona_logitech_finance_ready",
            ),
            "template_language": _whatsapp_template_setting(
                "finance_template_language",
                "WHATSAPP_FINANCE_TEMPLATE_LANGUAGE",
                "en",
            ),
            "body_parameters": [
                instance.approval_no,
                _user_display_name(instance.requested_by),
                _user_display_name(actor),
                str(instance.items.count()),
                str(instance.gross_requested),
                str(instance.tds_requested),
                str(instance.net_requested),
            ],
            "url_button_parameters": [str(instance.pk)],
        }
    if event_key in {"APPROVAL_COMPLETED", "APPROVAL_REJECTED", "CHANGES_REQUESTED"}:
        status = {
            "APPROVAL_COMPLETED": "Approved",
            "APPROVAL_REJECTED": "Rejected",
            "CHANGES_REQUESTED": "Changes requested",
        }[event_key]
        return {
            "template_name": _whatsapp_template_setting(
                "operations_approval_template_name",
                "WHATSAPP_OPERATIONS_APPROVAL_TEMPLATE_NAME",
                "drona_logitech_operations_approval",
            ),
            "template_language": _whatsapp_template_setting(
                "operations_approval_template_language",
                "WHATSAPP_OPERATIONS_APPROVAL_TEMPLATE_LANGUAGE",
                "en",
            ),
            "body_parameters": [
                instance.approval_no,
                status,
                _user_display_name(actor),
                str(instance.items.count()),
                str(instance.net_requested),
            ],
            "url_button_parameters": [str(instance.pk)],
        }
    if event_key == "PAYMENT_COMPLETED":
        paid_at = instance.paid_at or instance.updated_at
        return {
            "template_name": _whatsapp_template_setting(
                "operations_payment_template_name",
                "WHATSAPP_OPERATIONS_PAYMENT_TEMPLATE_NAME",
                "drona_logitech_operations_payment",
            ),
            "template_language": _whatsapp_template_setting(
                "operations_payment_template_language",
                "WHATSAPP_OPERATIONS_PAYMENT_TEMPLATE_LANGUAGE",
                "en",
            ),
            "body_parameters": [
                instance.payment_no,
                instance.vendor.display_name,
                str(instance.allocations.values("trip_id").distinct().count()),
                str(instance.gross_allocated_amount),
                str(instance.tds_amount),
                str(instance.net_paid_amount),
                instance.utr_reference,
                timezone.localtime(paid_at).strftime("%d %b %Y, %I:%M %p"),
            ],
            "url_button_parameters": [str(instance.pk)],
        }
    if event_key == "SETTLEMENT_PENDING":
        delivered_at = instance.actual_delivery_at or instance.updated_at
        return {
            "template_name": _whatsapp_template_setting(
                "operations_settlement_template_name",
                "WHATSAPP_OPERATIONS_SETTLEMENT_TEMPLATE_NAME",
                "drona_logitech_operations_settlement",
            ),
            "template_language": _whatsapp_template_setting(
                "operations_settlement_template_language",
                "WHATSAPP_OPERATIONS_SETTLEMENT_TEMPLATE_LANGUAGE",
                "en",
            ),
            "body_parameters": [
                instance.trip_no,
                f"{instance.origin} to {instance.destination}",
                instance.vendor.display_name,
                timezone.localtime(delivered_at).strftime("%d %b %Y, %I:%M %p"),
                str(instance.vendor_freight_rate),
            ],
            "url_button_parameters": [str(instance.pk)],
        }
    return None


@transaction.atomic
def process_whatsapp_approval_response(*, inbound_message, outbound_message, sender, payload):
    from accounts.models import User
    from approvals.models import ApprovalAction, PaymentApprovalBatch
    from approvals.services import decide_batch

    try:
        value = signing.TimestampSigner(salt=WHATSAPP_APPROVAL_SALT).unsign(
            payload,
            max_age=int(os.getenv("WHATSAPP_APPROVAL_EXPIRY_SECONDS", "604800")),
        )
    except signing.SignatureExpired as exc:
        raise ValueError("This WhatsApp approval button has expired") from exc
    except signing.BadSignature as exc:
        raise ValueError("Invalid WhatsApp approval button signature") from exc
    try:
        batch_id, user_id, decision_code = value.split(".")
        data = {
            "batch": int(batch_id),
            "user": int(user_id),
            "decision": {"A": "APPROVE", "R": "REJECT"}[decision_code],
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Unsupported WhatsApp approval response") from exc
    user = User.objects.filter(pk=data.get("user"), is_active=True).first()
    normalized_sender = re.sub(r"\D", "", sender or "")
    if not user or not user.whatsapp_phone or normalized_sender != user.whatsapp_phone:
        raise PermissionError("The WhatsApp sender does not match the assigned approver")
    if (
        not outbound_message
        or outbound_message.user_id != user.pk
        or outbound_message.event_key != "APPROVAL_REQUESTED"
        or str(outbound_message.object_id) != str(data.get("batch"))
    ):
        raise PermissionError("The reply is not linked to this approver's approval request")
    batch = PaymentApprovalBatch.objects.select_for_update().filter(pk=data["batch"]).first()
    if not batch:
        raise ValueError("The approval no longer exists")
    stage = batch.stage_decisions.filter(sequence=batch.current_stage).first()
    if stage and user.role != stage.role and user.role != User.Role.ADMIN:
        raise PermissionError("The sender is not assigned to the current approval stage")
    if not settings.WHATSAPP_INTERACTIVE_DECISIONS:
        raise PermissionError(
            "WhatsApp button decisions are disabled. Open the approval in the application to decide."
        )
    decision = (
        ApprovalAction.Action.APPROVE
        if data["decision"] == "APPROVE"
        else ApprovalAction.Action.REJECT
    )
    decision_label = "Approved" if data["decision"] == "APPROVE" else "Rejected"
    comment = f"{decision_label} from authenticated WhatsApp button by {user.username}"
    batch = decide_batch(batch=batch, actor=user, decision=decision, comment=comment)
    inbound_message.object_type = "approval"
    inbound_message.object_id = str(batch.pk)
    inbound_message.user = user
    inbound_message.raw_metadata = {
        **inbound_message.raw_metadata,
        "approval_decision": data["decision"],
        "decision_status": "RECORDED",
    }
    inbound_message.save(
        update_fields=["object_type", "object_id", "user", "raw_metadata", "updated_at"]
    )
    return batch


def emit_event(event_key, *, instance, actor=None):
    from accounts.models import User
    from approvals.models import PaymentApprovalBatch

    reference = (
        getattr(instance, "approval_no", None)
        or getattr(instance, "payment_no", None)
        or getattr(instance, "trip_no", None)
        or f"#{instance.pk}"
    )
    users = User.objects.none()
    if event_key == "APPROVAL_REQUESTED" and isinstance(instance, PaymentApprovalBatch):
        stage = instance.stage_decisions.filter(sequence=instance.current_stage).first()
        users = User.objects.filter(role=stage.role if stage else User.Role.APPROVER, is_active=True)
    elif event_key == "FINANCE_READY":
        users = User.objects.filter(role=User.Role.FINANCE, is_active=True)
    elif event_key == "PAYMENT_COMPLETED":
        users = User.objects.filter(
            requested_approvals__items__allocations__payment=instance, is_active=True
        ).distinct()
    elif event_key == "SETTLEMENT_PENDING":
        users = User.objects.filter(role=User.Role.OPERATIONS, is_active=True)
    elif event_key == "PAYMENT_FAILED":
        users = User.objects.filter(role__in=[User.Role.FINANCE, User.Role.ADMIN], is_active=True)
    elif hasattr(instance, "requested_by"):
        users = User.objects.filter(pk=instance.requested_by_id)
    action_url = ""
    web_origin = os.getenv("WEB_ORIGIN", "http://localhost:3000").rstrip("/")
    if event_key == "APPROVAL_REQUESTED" and isinstance(instance, PaymentApprovalBatch):
        action_url = f"{web_origin}/approvals/{instance.pk}"
    elif event_key == "FINANCE_READY":
        action_url = f"{web_origin}/finance?approval={instance.pk}"
    elif event_key in {"APPROVAL_COMPLETED", "APPROVAL_REJECTED", "CHANGES_REQUESTED"}:
        action_url = f"{web_origin}/approvals/{instance.pk}"
    elif event_key in {"PAYMENT_COMPLETED", "PAYMENT_FAILED"}:
        action_url = f"{web_origin}/payments/{instance.pk}"
    elif event_key == "SETTLEMENT_PENDING":
        action_url = f"{web_origin}/trips/{instance.pk}"
    context = {
        "reference": reference,
        "actor": getattr(actor, "username", "System"),
        "action_url": action_url,
        "gross": getattr(instance, "gross_requested", ""),
        "tds": getattr(instance, "tds_requested", ""),
        "net": getattr(instance, "net_requested", getattr(instance, "net_paid_amount", "")),
        "utr": getattr(instance, "utr_reference", ""),
    }
    external_channels = (
        (IntegrationMessage.Channel.EMAIL, "email"),
        (IntegrationMessage.Channel.WHATSAPP, "whatsapp_phone"),
    )
    approval_packet = None
    for user in users:
        destinations = [(IntegrationMessage.Channel.IN_APP, user.username)]
        if event_key in {
            "APPROVAL_REQUESTED",
            "FINANCE_READY",
            "APPROVAL_COMPLETED",
            "APPROVAL_REJECTED",
            "CHANGES_REQUESTED",
            "PAYMENT_COMPLETED",
            "SETTLEMENT_PENDING",
        }:
            destinations.extend(
                (channel, str(getattr(user, field, "") or "").strip())
                for channel, field in external_channels
            )
        for channel, recipient in destinations:
            if not recipient or NotificationPreference.objects.filter(
                user=user, event_key=event_key, channel=channel, enabled=False
            ).exists():
                continue
            subject, body = render_event(event_key, context, channel=channel)
            if channel != IntegrationMessage.Channel.IN_APP and action_url not in body:
                body = f"{body}\n\nOpen securely: {action_url}"
            provider_options = None
            if channel == IntegrationMessage.Channel.WHATSAPP and event_key == "APPROVAL_REQUESTED":
                if approval_packet is None:
                    from approvals.packet import ensure_approval_packet

                    approval_packet = ensure_approval_packet(instance, instance.requested_by)
                provider_options = approval_whatsapp_options(instance, user, approval_packet)
            elif channel == IntegrationMessage.Channel.WHATSAPP:
                provider_options = workflow_whatsapp_options(event_key, instance, actor=actor)
            event_marker = getattr(instance, "revision_no", 0)
            if event_key == "FINANCE_READY" and hasattr(instance, "items"):
                event_marker = f"{event_marker}:{instance.items.filter(item_status='APPROVED').count()}"
            legacy_key = (
                f"event:{event_key}:{instance._meta.label_lower}:{instance.pk}:"
                f"{getattr(instance, 'current_stage', 0)}:{user.pk}:{channel}"
            )
            if IntegrationMessage.objects.filter(idempotency_key=legacy_key).exists():
                # Rows queued before the marker was added keep their original key.
                continue
            queue_message(
                channel=channel,
                recipient=recipient,
                subject=subject,
                body=body,
                object_type=instance._meta.label_lower,
                object_id=instance.pk,
                idempotency_key=(
                    f"event:{event_key}:{instance._meta.label_lower}:{instance.pk}:"
                    f"{getattr(instance, 'current_stage', 0)}:{event_marker}:{user.pk}:{channel}"
                ),
                user=user,
                event_key=event_key,
                actor=actor,
                provider_options=provider_options,
            )


def emit_mention_events(comment):
    from accounts.models import User
    from operations.models import Trip
    from payments.models import FinancePaymentTransaction

    for user in comment.mentions.all():
        if user.role == User.Role.TRANSPORTER:
            if comment.visibility != comment.Visibility.TRANSPORTER_VISIBLE:
                continue
            if comment.object_type == "trip":
                context_vendor_id = Trip.objects.filter(pk=comment.object_id).values_list(
                    "vendor_id", flat=True
                ).first()
            elif comment.object_type == "payment":
                context_vendor_id = FinancePaymentTransaction.objects.filter(
                    pk=comment.object_id
                ).values_list("vendor_id", flat=True).first()
            else:
                context_vendor_id = None
            if not context_vendor_id or context_vendor_id != user.vendor_id:
                continue
        subject, body = render_event(
            "MENTION",
            {"reference": f"{comment.object_type} #{comment.object_id}", "actor": comment.author.username},
        )
        queue_message(
            channel="IN_APP",
            recipient=user.username,
            subject=subject,
            body=body,
            object_type=comment.object_type,
            object_id=comment.object_id,
            idempotency_key=f"mention:{comment.pk}:{user.pk}",
            user=user,
            event_key="MENTION",
            actor=comment.author,
        )


def transporter_payment_payload(payment):
    lines = payment.allocations.select_related("trip").filter(trip__vendor=payment.vendor)
    return {
        "vendor": payment.vendor.display_name,
        "payment_no": payment.payment_no,
        "payment_date": str(payment.payment_date),
        "utr_reference": payment.utr_reference,
        "trips": [
            {
                "trip_no": row.trip.trip_no,
                "route": f"{row.trip.origin} → {row.trip.destination}",
                "gross": str(row.gross_amount_allocated),
                "tds": str(row.tds_allocated),
                "net": str(row.net_cash_allocated),
            }
            for row in lines
        ],
    }


def persist_whatsapp_media(message, media):
    """Download, validate, and privately attach inbound WhatsApp media."""
    media_id = str((media or {}).get("id", ""))
    if not media_id or message.object_type not in {"approval", "trip", "payment"}:
        return None
    connection = _connection(IntegrationConnection.Provider.WHATSAPP)
    credentials = _connection_credentials(connection)
    token = credentials.get("access_token") or os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    version = os.getenv("WHATSAPP_API_VERSION", "v23.0")
    if not token:
        raise RuntimeError("WhatsApp is disconnected")
    metadata = request_json(
        f"https://graph.facebook.com/{version}/{media_id}", token=token
    )
    content, response_type = download_binary(metadata["url"], token=token)
    content_type = metadata.get("mime_type") or response_type

    from django.core.files.uploadedfile import SimpleUploadedFile

    from accounts.models import User
    from approvals.models import PaymentApprovalBatch
    from core.files import inspect_upload
    from operations.models import Document, Trip
    from payments.models import FinancePaymentTransaction

    actor = None
    if message.object_type == "approval":
        actor = (
            PaymentApprovalBatch.objects.filter(pk=message.object_id)
            .values_list("requested_by_id", flat=True)
            .first()
        )
    elif message.object_type == "payment":
        actor = (
            FinancePaymentTransaction.objects.filter(pk=message.object_id)
            .values_list("created_by_id", flat=True)
            .first()
        )
    elif message.object_type == "trip" and Trip.objects.filter(pk=message.object_id).exists():
        actor = User.objects.filter(role=User.Role.ADMIN, is_active=True).values_list("id", flat=True).first()
    if not actor:
        actor = User.objects.filter(role=User.Role.ADMIN, is_active=True).values_list("id", flat=True).first()
    if not actor:
        raise RuntimeError("No internal user is available to own the inbound attachment")
    extension = mimetypes.guess_extension(content_type) or ""
    filename = str(media.get("filename") or f"whatsapp-{media_id}{extension}")[:255]
    upload = SimpleUploadedFile(filename, content, content_type=content_type)
    inspection = inspect_upload(upload)
    document = Document.objects.create(
        object_type=message.object_type,
        object_id=message.object_id,
        kind=Document.Kind.OTHER,
        file=upload,
        original_name=filename,
        content_type=inspection.content_type,
        size=upload.size,
        uploaded_by_id=actor,
        sha256=inspection.sha256,
        scan_status=inspection.status,
        scan_detail=inspection.detail,
    )
    message.raw_metadata = {**message.raw_metadata, "attachment_id": document.pk}
    message.save(update_fields=["raw_metadata", "updated_at"])
    return document


def _email_reply_author(batch, sender, outbound=None):
    """Resolve the inbound sender to a user allowed to comment on this approval, or None.

    The sender address is client-supplied, so it is only trusted when it matches the
    approver the outbound mail was sent to, a transporter login of one of the batch
    vendors, or the registered email of one of those vendors.
    """
    from accounts.models import User
    from operations.models import Vendor

    match = re.search(r"[\w.+-]+@[\w.-]+", sender or "")
    email = match.group(0).lower() if match else ""
    if not email:
        return None
    if outbound and outbound.user_id and outbound.user.is_active and outbound.user.email.lower() == email:
        return outbound.user
    vendor_ids = list(batch.items.values_list("vendor_id", flat=True))
    transporter = (
        User.objects.filter(role=User.Role.TRANSPORTER, vendor_id__in=vendor_ids, is_active=True, email__iexact=email)
        .order_by("pk")
        .first()
    )
    if transporter:
        return transporter
    vendor = Vendor.objects.filter(pk__in=vendor_ids, email__iexact=email).order_by("pk").first()
    if vendor:
        # Verified vendor address without a transporter login: file it under the requester,
        # the comment body still names the actual sender.
        transporter = User.objects.filter(role=User.Role.TRANSPORTER, vendor=vendor, is_active=True).order_by("pk").first()
        return transporter or batch.requested_by
    return None


def ingest_email_reply(*, external_message_id, external_thread_id, subject, body, sender=""):
    from approvals.models import Comment, PaymentApprovalBatch

    message, created = IntegrationMessage.objects.get_or_create(
        idempotency_key=f"email-inbound:{external_message_id}",
        defaults={
            "channel": IntegrationMessage.Channel.EMAIL,
            "direction": "INBOUND",
            "external_message_id": external_message_id,
            "external_thread_id": external_thread_id,
            "object_type": "unmapped",
            "object_id": "",
            "recipient": sender,
            "subject": subject[:240],
            "body_summary": body[:1000],
            "status": "RECEIVED",
            "received_at": timezone.now(),
        },
    )
    if not created:
        return message
    outbound = None
    if external_thread_id:
        # An empty thread id must never match: SMTP outbound records carry no thread.
        outbound = (
            IntegrationMessage.objects.filter(
                channel=IntegrationMessage.Channel.EMAIL,
                external_thread_id=external_thread_id,
                direction="OUTBOUND",
            )
            .exclude(object_type="unmapped")
            .select_related("user")
            .order_by("-id")
            .first()
        )
    batch = None
    if outbound and outbound.object_type in {"approval", "approvals.paymentapprovalbatch"}:
        batch = PaymentApprovalBatch.objects.filter(pk=outbound.object_id).first()
    if batch is None:
        match = re.search(r"\[(PA-\d{4}-\d{6})\]", subject or "")
        if match:
            batch = PaymentApprovalBatch.objects.filter(approval_no=match.group(1)).first()
    approval_types = {"approval", "approvals.paymentapprovalbatch"}
    if batch and outbound and (
        outbound.object_type not in approval_types or str(outbound.object_id) != str(batch.pk)
    ):
        # A thread match for another object must not vouch for a batch found via the subject.
        outbound = None
    author = _email_reply_author(batch, sender, outbound) if batch else None
    if batch and author:
        message.object_type = "approval"
        message.object_id = str(batch.pk)
        message.user = author
        message.save(update_fields=["object_type", "object_id", "user", "updated_at"])
        Comment.objects.create(
            object_type="approval",
            object_id=str(batch.pk),
            author=author,
            body=f"Email reply from {sender}:\n\n{body}",
            visibility=Comment.Visibility.INTERNAL,
        )
    else:
        reason = (
            "Sender is not a registered contact for this approval's vendors or approver"
            if batch
            else "No matching thread or approval reference"
        )
        UnmappedInboundMessage.objects.get_or_create(message=message, defaults={"reason": reason})
    return message
