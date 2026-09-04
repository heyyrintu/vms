import json

import pytest
from django.utils import timezone
from pypdf import PdfReader
from rest_framework.test import APIClient

from accounts.models import User
from approvals.models import ApprovalAction, PaymentApprovalBatch
from approvals.packet import build_approval_packet_pdf
from approvals.services import create_approval_batch, submit_batch
from core.crypto import decrypt_value, encrypt_value
from integrations.models import IntegrationConnection, IntegrationMessage
from integrations.providers import WhatsAppProvider
from integrations.services import deliver_message, get_provider, process_whatsapp_approval_response
from operations.models import Document


@pytest.mark.django_db
def test_approval_request_queues_pdf_and_signed_quick_reply_buttons(
    monkeypatch, trip_factory, users, tmp_path, settings
):
    settings.MEDIA_ROOT = tmp_path
    monkeypatch.setenv("WHATSAPP_APPROVAL_TEMPLATE_NAME", "drona_logitech_approval_review")
    approver = users[User.Role.APPROVER]
    approver.whatsapp_phone = "919811111111"
    approver.save(update_fields=["whatsapp_phone"])
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip_factory(1)])

    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])

    message = IntegrationMessage.objects.get(
        user=approver,
        channel=IntegrationMessage.Channel.WHATSAPP,
        event_key="APPROVAL_REQUESTED",
    )
    payload = json.loads(decrypt_value(message.payload_encrypted))
    options = payload["provider_options"]
    document = Document.objects.get(pk=options["document_id"])
    assert document.kind == Document.Kind.APPROVAL_PACKET
    assert document.scan_status == "CLEAN"
    assert options["template_name"] == "drona_logitech_approval_review"
    assert options["body_parameters"] == [
        batch.approval_no,
        "operations",
        "1",
        "47500.00",
        "450.00",
        "47050.00",
    ]
    assert len(options["quick_reply_payloads"]) == 2
    assert all(len(value) <= 128 for value in options["quick_reply_payloads"])
    message = deliver_message(message)
    assert message.status == "SENT"
    assert message.raw_metadata["has_document"] is True
    assert message.raw_metadata["quick_reply_count"] == 2


@pytest.mark.django_db
def test_authenticated_whatsapp_approve_button_records_decision_once(
    monkeypatch, trip_factory, users, tmp_path, settings
):
    settings.MEDIA_ROOT = tmp_path
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    approver = users[User.Role.APPROVER]
    approver.whatsapp_phone = "919811111111"
    approver.save(update_fields=["whatsapp_phone"])
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip_factory(1)])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    outbound = IntegrationMessage.objects.get(
        user=approver,
        channel="WHATSAPP",
        event_key="APPROVAL_REQUESTED",
    )
    outbound.external_message_id = "wamid-approval-request-1"
    outbound.status = "SENT"
    outbound.save(update_fields=["external_message_id", "status", "updated_at"])
    options = json.loads(decrypt_value(outbound.payload_encrypted))["provider_options"]
    approve_payload = options["quick_reply_payloads"][0]
    webhook = {
        "entry": [{"changes": [{"value": {"messages": [{
            "from": approver.whatsapp_phone,
            "id": "wamid-approval-reply-1",
            "timestamp": str(int(timezone.now().timestamp())),
            "type": "button",
            "context": {"id": outbound.external_message_id},
            "button": {"text": "Approve", "payload": approve_payload},
        }]}}]}],
    }
    client = APIClient()

    first = client.post("/api/webhooks/whatsapp/", webhook, format="json")
    second = client.post("/api/webhooks/whatsapp/", webhook, format="json")

    assert first.status_code == 200
    assert second.status_code == 200
    batch.refresh_from_db()
    assert batch.status == PaymentApprovalBatch.Status.APPROVED
    assert batch.actions.filter(action=ApprovalAction.Action.APPROVE).count() == 1
    inbound = IntegrationMessage.objects.get(external_message_id="wamid-approval-reply-1")
    assert inbound.user == approver
    assert inbound.raw_metadata["approval_decision"] == "APPROVE"
    assert inbound.raw_metadata["decision_status"] == "RECORDED"


@pytest.mark.django_db
def test_whatsapp_approval_rejects_spoofed_sender(monkeypatch, trip_factory, users, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    approver = users[User.Role.APPROVER]
    approver.whatsapp_phone = "919811111111"
    approver.save(update_fields=["whatsapp_phone"])
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip_factory(1)])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    outbound = IntegrationMessage.objects.get(user=approver, channel="WHATSAPP")
    outbound.external_message_id = "wamid-secure-request"
    outbound.save(update_fields=["external_message_id", "updated_at"])
    approve_payload = json.loads(decrypt_value(outbound.payload_encrypted))["provider_options"]["quick_reply_payloads"][0]
    webhook = {"entry": [{"changes": [{"value": {"messages": [{
        "from": "919899999999",
        "id": "wamid-spoofed-reply",
        "type": "button",
        "context": {"id": outbound.external_message_id},
        "button": {"text": "Approve", "payload": approve_payload},
    }]}}]}]}

    response = APIClient().post("/api/webhooks/whatsapp/", webhook, format="json")

    assert response.status_code == 200
    batch.refresh_from_db()
    assert batch.status == PaymentApprovalBatch.Status.PENDING
    inbound = IntegrationMessage.objects.get(external_message_id="wamid-spoofed-reply")
    assert inbound.raw_metadata["decision_status"] == "REJECTED"
    assert "sender" in inbound.raw_metadata["approval_error"].lower()


@pytest.mark.django_db
def test_authenticated_whatsapp_reject_button_records_reason(trip_factory, users, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    approver = users[User.Role.APPROVER]
    approver.whatsapp_phone = "919811111111"
    approver.save(update_fields=["whatsapp_phone"])
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip_factory(1)])
    submit_batch(batch=batch, actor=users[User.Role.OPERATIONS])
    outbound = IntegrationMessage.objects.get(user=approver, channel="WHATSAPP")
    reject_payload = json.loads(decrypt_value(outbound.payload_encrypted))["provider_options"]["quick_reply_payloads"][1]
    inbound = IntegrationMessage.objects.create(
        channel="WHATSAPP",
        direction="INBOUND",
        idempotency_key="whatsapp-reject-reply",
        external_message_id="wamid-reject-reply",
        object_type="approval",
        object_id=str(batch.pk),
        recipient=approver.whatsapp_phone,
        status="RECEIVED",
    )

    process_whatsapp_approval_response(
        inbound_message=inbound,
        outbound_message=outbound,
        sender=approver.whatsapp_phone,
        payload=reject_payload,
    )

    batch.refresh_from_db()
    assert batch.status == PaymentApprovalBatch.Status.REJECTED
    action = batch.actions.get(action=ApprovalAction.Action.REJECT)
    assert "authenticated WhatsApp button" in action.comment


def test_whatsapp_provider_builds_document_template_and_buttons(monkeypatch):
    captured = {}
    provider = WhatsAppProvider(
        access_token="token",
        phone_number_id="phone-id",
        api_version="v23.0",
    )
    monkeypatch.setattr(provider, "_upload_document", lambda document: "media-id-1")

    def capture_request(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return {"messages": [{"id": "wamid-sent-1"}]}

    monkeypatch.setattr("integrations.providers.request_json", capture_request)
    provider.send(
        recipient="919811111111",
        subject="Approval",
        body="Fallback body",
        idempotency_key="approval-1",
        options={
            "template_name": "drona_logitech_approval_review",
            "template_language": "en",
            "body_parameters": ["PA-1", "Operations", "1", "50000", "500", "49500"],
            "quick_reply_payloads": ["signed-approve", "signed-reject"],
            "url_button_parameters": ["123"],
            "document": {"filename": "approval.pdf", "content_type": "application/pdf", "content": b"%PDF"},
        },
    )

    template = captured["payload"]["template"]
    assert template["name"] == "drona_logitech_approval_review"
    assert template["components"][0]["parameters"][0]["document"]["id"] == "media-id-1"
    assert template["components"][-3]["parameters"][0]["payload"] == "signed-approve"
    assert template["components"][-2]["sub_type"] == "quick_reply"
    assert template["components"][-2]["parameters"][0]["payload"] == "signed-reject"
    assert template["components"][-1]["sub_type"] == "url"
    assert template["components"][-1]["parameters"][0]["text"] == "123"


@pytest.mark.django_db
def test_connected_whatsapp_configuration_selects_live_provider_without_env(monkeypatch):
    monkeypatch.delenv("WHATSAPP_PROVIDER", raising=False)
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID", raising=False)
    IntegrationConnection.objects.create(
        provider=IntegrationConnection.Provider.WHATSAPP,
        status="CONNECTED",
        encrypted_credentials=encrypt_value(
            json.dumps({"access_token": "stored-token", "phone_number_id": "stored-phone-id"})
        ),
    )

    provider = get_provider(IntegrationMessage.Channel.WHATSAPP)

    assert isinstance(provider, WhatsAppProvider)
    assert provider.access_token == "stored-token"
    assert provider.phone_number_id == "stored-phone-id"


@pytest.mark.django_db
def test_generated_approval_pdf_is_readable(trip_factory, users):
    batch = create_approval_batch(actor=users[User.Role.OPERATIONS], trips=[trip_factory(1)])
    batch.submitted_at = timezone.now()
    batch.save(update_fields=["submitted_at", "updated_at"])

    content = build_approval_packet_pdf(batch)
    reader = PdfReader(__import__("io").BytesIO(content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert batch.approval_no in text
    assert "Payment approval review" in text
    assert "Freight 100%" in text
    assert "Net payable" in text
