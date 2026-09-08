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
    assert options["body_parameters"] == [code, "Drona Logitech"]


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


# The approved Meta templates `vms_login` (1738923667316316) and
# `password_recovery` (1639963370986997) are both AUTHENTICATION category,
# registered under language `en_US`, and each carries a copy-code URL button
# whose link embeds `{{1}}`. Meta rejects a send that names language `en`
# (132001, no such translation) or that omits the button component for a
# button that takes a variable (132000, parameter count mismatch). These pin
# the defaults to what the live templates actually require.
@pytest.mark.django_db
@pytest.mark.parametrize(
    "purpose",
    [OtpChallenge.Purpose.LOGIN, OtpChallenge.Purpose.PASSWORD_RESET],
)
def test_otp_templates_default_to_the_registered_en_us_translation(
    member, settings, monkeypatch, purpose
):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    for name in (
        "WHATSAPP_LOGIN_OTP_TEMPLATE_LANGUAGE",
        "WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_LANGUAGE",
    ):
        monkeypatch.delenv(name, raising=False)
    challenge, code = otp.issue_challenge(
        member, purpose=purpose, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert options["template_language"] == "en_US"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "purpose",
    [OtpChallenge.Purpose.LOGIN, OtpChallenge.Purpose.PASSWORD_RESET],
)
def test_otp_templates_default_to_sending_the_copy_code_button(
    member, settings, monkeypatch, purpose
):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    monkeypatch.delenv("WHATSAPP_OTP_BUTTON_TYPE", raising=False)
    challenge, code = otp.issue_challenge(
        member, purpose=purpose, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert options["otp_button_type"] == "url"
    assert options["otp_button_code"] == code


# Meta caps every body parameter of an AUTHENTICATION template at 15 characters
# and rejects the whole send with 132018 when one is longer. OTP_APP_LABEL is
# operator-configurable, so clamp it rather than let a long label silently stop
# every login code from being delivered.
@pytest.mark.django_db
def test_login_body_parameters_stay_within_the_meta_auth_parameter_limit(
    member, settings, monkeypatch
):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    settings.OTP_APP_LABEL = "An Extremely Long Product Name"
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.WHATSAPP
    )
    message = otp.send_challenge(challenge, code)
    options = json.loads(decrypt_value(message.payload_encrypted))["provider_options"]
    assert all(len(str(p)) <= 15 for p in options["body_parameters"])


@pytest.mark.django_db
def test_default_app_label_fits_the_auth_template_parameter_limit(settings):
    assert len(settings.OTP_APP_LABEL) <= 15
