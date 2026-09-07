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


def test_whatsapp_copy_code_button_component(monkeypatch):
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
            "otp_button_type": "copy_code",
            "otp_button_code": "123456",
        },
    )
    components = sent["payload"]["template"]["components"]
    assert components[-1] == {
        "type": "button",
        "sub_type": "copy_code",
        "index": "0",
        "parameters": [{"type": "coupon_code", "coupon_code": "123456"}],
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
