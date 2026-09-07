import json

import pytest

from accounts import otp
from accounts.models import OtpChallenge, User
from core.crypto import decrypt_value
from integrations.models import IntegrationMessage


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member", email="member@drona.test", whatsapp_phone="919811111111"
    )


@pytest.mark.django_db
def test_whatsapp_login_code_uses_vms_login_template(member, settings, monkeypatch):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    monkeypatch.delenv("WHATSAPP_LOGIN_OTP_TEMPLATE_NAME", raising=False)
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert message.channel == IntegrationMessage.Channel.WHATSAPP
    assert message.recipient == "919811111111"
    assert options["template_name"] == "vms_login"
    assert options["body_parameters"] == [code, "Drona Logitech VMS"]


@pytest.mark.django_db
def test_password_reset_code_uses_password_recovery_template(member, settings, monkeypatch):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    monkeypatch.delenv("WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_NAME", raising=False)
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.PASSWORD_RESET, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert options["template_name"] == "password_recovery"
    assert options["body_parameters"] == [code]
    assert options["otp_button_code"] == code


@pytest.mark.django_db
def test_code_is_redacted_from_every_readable_field(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    message = otp.send_challenge(challenge, code)
    assert code not in message.subject
    assert code not in message.body_summary
    assert code in json.loads(decrypt_value(message.payload_encrypted))["body"]
    assert message.event_key == "LOGIN_OTP"
    assert message.idempotency_key == f"otp:{challenge.id}"
