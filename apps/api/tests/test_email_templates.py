import json

import pytest

from core.crypto import decrypt_value
from integrations.email_builder import build_document, render_email_html
from integrations.models import IntegrationMessage
from integrations.providers import SMTPProvider
from integrations.services import build_html_body, deliver_message, queue_message
from tests.test_smtp import FakeSMTPClient


def _blocks(document, kind):
    return [value for block_kind, value in document["blocks"] if block_kind == kind]


def test_cta_line_keeps_the_sentence_before_the_link():
    # The whole line used to be consumed by the button, dropping "Net payable".
    document = build_document(
        subject="Approval requested",
        body=(
            "Approval PA-2026-000418 is waiting for your decision. Net payable: 2,47,500.00. "
            "Review securely: https://vms.example.test/approvals/418"
        ),
        event_key="APPROVAL_REQUESTED",
    )

    assert "Approval PA-2026-000418 is waiting for your decision." in _blocks(document, "paragraph")
    assert _blocks(document, "facts") == [[("Net payable", "2,47,500.00")]]
    assert _blocks(document, "button") == [
        {"url": "https://vms.example.test/approvals/418", "label": "Review approval"}
    ]
    assert document["eyebrow"] == "PA-2026-000418"


def test_pipe_delimited_lines_become_line_items_with_metrics():
    document = build_document(
        subject="[PAY-1] payment confirmation",
        body=(
            "Payment PAY-1 processed on 2026-09-08.\n"
            "TRIP-9 | Bhiwandi -> Hyderabad | Gross 125000.00 | TDS 1250.00 | Net 123750.00\n"
            "UTR: HDFCN5202609081"
        ),
        event_key="PAYMENT_COMPLETED",
        object_type="payment",
    )

    assert _blocks(document, "items") == [
        [
            {
                "title": "TRIP-9",
                "subtitle": "Bhiwandi -> Hyderabad",
                "metrics": [("Gross", "125000.00"), ("TDS", "1250.00"), ("Net", "123750.00")],
            }
        ]
    ]
    assert _blocks(document, "facts") == [[("UTR", "HDFCN5202609081")]]


def test_otp_body_renders_a_code_block_with_readable_sentences():
    document = build_document(
        subject="Your Drona Logitech sign-in code",
        body=(
            "OTP Code: 481902. This is your OTP code for Drona Logitech VMS. "
            "For your security, do not share this code. It expires in 5 minutes."
        ),
        event_key="LOGIN_OTP",
        object_type="account",
    )

    code_blocks = _blocks(document, "code")
    assert len(code_blocks) == 1
    assert code_blocks[0]["code"] == "481902"
    # Splitting on the code must not strip the sentence punctuation around it.
    assert code_blocks[0]["note"] == (
        "This is your OTP code for Drona Logitech VMS. "
        "For your security, do not share this code. It expires in 5 minutes."
    )
    assert "481902" not in " ".join(_blocks(document, "paragraph"))


def test_password_reset_drops_the_fragment_left_by_the_code():
    document = build_document(
        subject="Your Drona Logitech password recovery code",
        body=(
            "702514 is your password recovery code. For your security, do not share this "
            "code. It expires in 5 minutes."
        ),
        event_key="PASSWORD_RESET_OTP",
    )

    assert _blocks(document, "code")[0]["note"].startswith("For your security")


def test_rendered_html_escapes_record_content():
    html = render_email_html(
        subject="Approval completed",
        body='Vendor <script>alert("x")</script> & Co accepted the terms.',
        event_key="APPROVAL_COMPLETED",
    )

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; Co" in html


def test_rendered_html_carries_the_branded_shell():
    html = render_email_html(
        subject="Approval requested",
        body="Approval PA-1 needs a decision. Review securely: https://vms.example.test/approvals/1",
        event_key="APPROVAL_REQUESTED",
    )

    assert html.startswith("<!DOCTYPE html")
    assert "DRONA LOGITECH" in html.upper()
    assert 'href="https://vms.example.test/approvals/1"' in html
    assert "prefers-color-scheme:dark" in html
    assert "max-width:620px" in html


def test_smtp_provider_sends_multipart_alternative_with_text_fallback(monkeypatch):
    FakeSMTPClient.instances.clear()
    monkeypatch.setattr("integrations.providers.smtplib.SMTP", FakeSMTPClient)
    provider = SMTPProvider(
        host="smtp.example.test",
        port=587,
        from_email="transport@example.test",
        from_name="Drona Logitech",
        reply_to="ops@example.test",
    )

    provider.send(
        recipient="vendor@example.test",
        subject="Payment complete",
        body="Payment PAY-1 has been recorded.",
        idempotency_key="payment-email:1",
        options={"html_body": "<html><body>Payment PAY-1</body></html>"},
    )

    message = FakeSMTPClient.instances[0].message
    assert message.get_content_type() == "multipart/alternative"
    assert message["From"] == "Drona Logitech <transport@example.test>"
    assert message["Reply-To"] == "ops@example.test"
    assert message["Date"]
    assert message.get_body(("plain",)).get_content().strip() == "Payment PAY-1 has been recorded."
    assert "Payment PAY-1" in message.get_body(("html",)).get_content()


def test_smtp_attachments_keep_the_branded_html_body(monkeypatch):
    FakeSMTPClient.instances.clear()
    monkeypatch.setattr("integrations.providers.smtplib.SMTP", FakeSMTPClient)
    provider = SMTPProvider(host="smtp.example.test", port=587, from_email="t@example.test")

    result = provider.send(
        recipient="accounts@example.test",
        subject="Payment ready",
        body="Approved payable PA-1 is ready for finance.",
        idempotency_key="finance-email:1",
        options={
            "html_body": "<html><body>Ready for payment</body></html>",
            "attachments": [
                {
                    "filename": "V-900-POD-scan.pdf",
                    "content_type": "application/pdf",
                    "content": b"%PDF-1.4\npod\n",
                },
                {
                    "filename": "V-900-PAN-card.png",
                    "content_type": "image/png",
                    "content": b"\x89PNG\r\n\x1a\npan",
                },
            ],
        },
    )

    message = FakeSMTPClient.instances[0].message
    # add_attachment() promotes the message to mixed; the alternative pair - and so
    # the branded layout - has to survive that or every finance email loses its HTML.
    assert message.get_content_type() == "multipart/mixed"
    assert message.get_body(("plain",)).get_content().strip() == (
        "Approved payable PA-1 is ready for finance."
    )
    assert "Ready for payment" in message.get_body(("html",)).get_content()
    attachments = list(message.iter_attachments())
    assert [part.get_filename() for part in attachments] == [
        "V-900-POD-scan.pdf",
        "V-900-PAN-card.png",
    ]
    assert [part.get_content_type() for part in attachments] == ["application/pdf", "image/png"]
    assert attachments[0].get_payload(decode=True) == b"%PDF-1.4\npod\n"
    assert result.metadata["attachment_count"] == 2


def test_smtp_provider_stays_plain_text_without_html(monkeypatch):
    FakeSMTPClient.instances.clear()
    monkeypatch.setattr("integrations.providers.smtplib.SMTP", FakeSMTPClient)
    provider = SMTPProvider(host="smtp.example.test", port=587, from_email="t@example.test")

    provider.send(
        recipient="vendor@example.test",
        subject="Payment complete",
        body="Payment PAY-1 has been recorded.",
        idempotency_key="payment-email:2",
    )

    message = FakeSMTPClient.instances[0].message
    assert message.get_content_type() == "text/plain"
    assert message["From"] == "t@example.test"


def test_build_html_body_falls_back_to_plain_text_when_rendering_breaks(monkeypatch):
    def explode(**kwargs):
        raise ValueError("layout is broken")

    monkeypatch.setattr("integrations.services.render_email_html", explode)

    assert build_html_body(subject="Anything", body="Body", event_key="APPROVAL_REQUESTED") == ""


@pytest.mark.django_db
def test_email_delivery_attaches_html_but_whatsapp_does_not(monkeypatch, users):
    sent = []

    class RecordingProvider:
        def send(self, *, recipient, subject, body, idempotency_key, options=None):
            sent.append(options or {})

            class Result:
                message_id = "id-1"
                thread_id = ""
                status = "SENT"
                metadata = {}

            return Result()

    monkeypatch.setattr("integrations.services.get_provider", lambda channel: RecordingProvider())

    for channel, key in (
        (IntegrationMessage.Channel.EMAIL, "html-email-1"),
        (IntegrationMessage.Channel.WHATSAPP, "html-whatsapp-1"),
    ):
        message = queue_message(
            channel=channel,
            recipient="someone@example.test",
            subject="Approval requested",
            body="Approval PA-1 needs a decision.",
            object_type="approval",
            object_id="1",
            idempotency_key=key,
            event_key="APPROVAL_REQUESTED",
        )
        deliver_message(message)

    email_options, whatsapp_options = sent
    assert "Approval requested" in email_options["html_body"]
    assert "html_body" not in whatsapp_options


@pytest.mark.django_db
def test_queued_payload_still_stores_only_the_plain_text_body(users):
    message = queue_message(
        channel=IntegrationMessage.Channel.EMAIL,
        recipient="someone@example.test",
        subject="Approval requested",
        body="Approval PA-1 needs a decision.",
        object_type="approval",
        object_id="1",
        idempotency_key="plain-payload-1",
        event_key="APPROVAL_REQUESTED",
    )

    # HTML is rendered at delivery time, so a layout change reaches queued mail too.
    payload = json.loads(decrypt_value(message.payload_encrypted))
    assert payload["body"] == "Approval PA-1 needs a decision."
    assert "html_body" not in payload["provider_options"]
