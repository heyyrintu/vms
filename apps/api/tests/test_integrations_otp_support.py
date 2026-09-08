import json

import pytest

from core.crypto import decrypt_value
from integrations.models import IntegrationMessage
from integrations.providers import WhatsAppProvider
from integrations.services import queue_message


@pytest.mark.django_db
def test_queue_message_summary_override_keeps_body_out_of_the_log(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    message = queue_message(
        channel=IntegrationMessage.Channel.EMAIL,
        recipient="member@drona.test",
        subject="Your code",
        body="Your code is 123456",
        object_type="account",
        object_id="1",
        idempotency_key="otp:test-1",
        summary="Sign-in code sent (code redacted)",
    )
    assert message.body_summary == "Sign-in code sent (code redacted)"
    assert "123456" not in message.body_summary
    assert "123456" in json.loads(decrypt_value(message.payload_encrypted))["body"]


@pytest.mark.django_db
def test_queue_message_defaults_summary_to_the_body(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    message = queue_message(
        channel=IntegrationMessage.Channel.IN_APP,
        recipient="",
        subject="Hello",
        body="Body text",
        object_type="account",
        object_id="1",
        idempotency_key="otp:test-2",
    )
    assert message.body_summary == "Body text"


@pytest.mark.django_db
def test_queue_message_truncates_a_caller_supplied_summary_to_1000_chars(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    long_summary = "s" * 1500
    message = queue_message(
        channel=IntegrationMessage.Channel.EMAIL,
        recipient="member@drona.test",
        subject="Your code",
        body="Your code is 123456",
        object_type="account",
        object_id="1",
        idempotency_key="otp:test-5",
        summary=long_summary,
    )
    assert len(message.body_summary) == 1000
    assert message.body_summary == long_summary[:1000]


@pytest.mark.django_db
def test_queue_message_truncates_the_body_default_summary_to_1000_chars(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    long_body = "b" * 1500
    message = queue_message(
        channel=IntegrationMessage.Channel.IN_APP,
        recipient="",
        subject="Hello",
        body=long_body,
        object_type="account",
        object_id="1",
        idempotency_key="otp:test-6",
    )
    assert len(message.body_summary) == 1000
    assert message.body_summary == long_body[:1000]


def test_whatsapp_authentication_template_sends_the_code_in_the_body_only(monkeypatch):
    """Meta rejects a COPY_CODE authentication send that also carries a button.

    The platform copies the code out of the body component itself. `sub_type`
    "copy_code" with a `coupon_code` parameter belongs to marketing coupon
    templates, and using it here returns 400.
    """
    sent = {}
    monkeypatch.setattr(
        "integrations.providers.request_json",
        lambda url, **kwargs: sent.update(kwargs) or {"messages": [{"id": "wamid.1"}]},
    )
    provider = WhatsAppProvider(access_token="t", phone_number_id="1")
    provider.send(
        recipient="919811111111",
        subject="",
        body="ignored",
        idempotency_key="otp:test-3",
        options={
            "template_name": "password_recovery",
            "body_parameters": ["123456"],
            # Passed explicitly so this pins the copy_code path itself, not the
            # default. Re-adding a copy_code button branch must fail here.
            "otp_button_type": "copy_code",
            "otp_button_code": "123456",
        },
    )
    components = sent["payload"]["template"]["components"]
    assert all(component["type"] != "button" for component in components)
    assert components == [{"type": "body", "parameters": [{"type": "text", "text": "123456"}]}]


def test_whatsapp_one_tap_template_carries_the_code_in_a_url_button(monkeypatch):
    """ONE_TAP authentication templates are the only ones that take a button."""
    sent = {}
    monkeypatch.setattr(
        "integrations.providers.request_json",
        lambda url, **kwargs: sent.update(kwargs) or {"messages": [{"id": "wamid.5"}]},
    )
    provider = WhatsAppProvider(access_token="t", phone_number_id="1")
    provider.send(
        recipient="919811111111",
        subject="",
        body="ignored",
        idempotency_key="otp:test-7",
        options={
            "template_name": "vms_login",
            "body_parameters": ["123456"],
            "otp_button_type": "url",
            "otp_button_code": "123456",
        },
    )
    assert sent["payload"]["template"]["components"][-1] == {
        "type": "button",
        "sub_type": "url",
        "index": "0",
        "parameters": [{"type": "text", "text": "123456"}],
    }


def test_whatsapp_omits_the_button_by_default(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "integrations.providers.request_json",
        lambda url, **kwargs: sent.update(kwargs) or {"messages": [{"id": "wamid.2"}]},
    )
    provider = WhatsAppProvider(access_token="t", phone_number_id="1")
    provider.send(
        recipient="919811111111",
        subject="",
        body="ignored",
        idempotency_key="otp:test-4",
        options={"template_name": "vms_login", "body_parameters": ["123456", "Drona Logitech VMS"]},
    )
    components = sent["payload"]["template"]["components"]
    assert all(component["type"] != "button" for component in components)
