import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import Lower
from django.utils import timezone

from .models import OtpChallenge, User

CODE_TTL = timedelta(minutes=5)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5
RESET_TICKET_MAX_AGE = 600


class OtpInvalid(Exception):
    """The challenge does not exist, has expired, is spent, or the code is wrong."""


class OtpRateLimited(Exception):
    """The user has asked for codes too often."""


def normalise_phone(value):
    return re.sub(r"[\s()+-]", "", value or "")


def hash_code(challenge_id, code):
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{challenge_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def mask_destination(identifier):
    if "@" in identifier:
        name, _, domain = identifier.partition("@")
        return f"{name[:1] or '*'}***@{domain}"
    digits = normalise_phone(identifier)
    if len(digits) < 8:
        return "*" * 8
    return f"+{digits[:2]} {digits[2:4]}****{digits[-4:]}"


def resolve_identifier(identifier):
    identifier = (identifier or "").strip()
    if "@" in identifier:
        user = (
            User.objects.annotate(email_ci=Lower("email"))
            .filter(email_ci=identifier.lower(), is_active=True)
            .exclude(email="")
            .first()
        )
        return user, OtpChallenge.Channel.EMAIL
    digits = normalise_phone(identifier)
    user = (
        User.objects.filter(whatsapp_phone=digits, is_active=True).first() if digits else None
    )
    return user, OtpChallenge.Channel.WHATSAPP


@transaction.atomic
def issue_challenge(user, *, purpose, channel, request=None):
    # Lock the user row for the whole check-then-write. Without it two concurrent
    # requests both read the rate-limit counts before either inserts, so both pass
    # and the user gets more live codes — and more delivered messages — than
    # MAX_PER_HOUR allows.
    locked_user = User.objects.select_for_update().get(pk=user.pk)
    now = timezone.now()
    recent = OtpChallenge.objects.filter(
        user=locked_user, purpose=purpose, created_at__gte=now - timedelta(hours=1)
    )
    if recent.filter(created_at__gt=now - RESEND_COOLDOWN).exists():
        raise OtpRateLimited("A code was sent moments ago")
    if recent.count() >= MAX_PER_HOUR:
        raise OtpRateLimited("Too many codes requested in the last hour")

    OtpChallenge.objects.filter(
        user=locked_user, purpose=purpose, consumed_at__isnull=True
    ).update(consumed_at=now)
    destination = (
        locked_user.email if channel == OtpChallenge.Channel.EMAIL else locked_user.whatsapp_phone
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OtpChallenge(
        user=locked_user,
        purpose=purpose,
        channel=channel,
        destination_masked=mask_destination(destination),
        expires_at=now + CODE_TTL,
        request_ip=_client_ip(request),
    )
    # The UUID default is applied in __init__, so the id is available for hashing pre-save.
    challenge.code_hash = hash_code(challenge.id, code)
    challenge.save()
    return challenge, code


def _client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def verify_challenge(challenge_id, code, *, purpose):
    # The failed-attempt increment below must survive even though this function
    # ultimately raises OtpInvalid: raising while still inside an atomic block
    # rolls back everything written in that block, including a save that
    # happened moments earlier. So the wrong-code branch only flags `invalid`
    # and lets the `with` block exit (and commit its savepoint) normally;
    # the actual raise happens after the transaction has already closed.
    invalid = False
    with transaction.atomic():
        try:
            challenge = OtpChallenge.objects.select_for_update().get(
                pk=challenge_id, purpose=purpose
            )
        except (OtpChallenge.DoesNotExist, ValueError, TypeError, ValidationError):
            raise OtpInvalid("Invalid or expired code") from None
        if (
            challenge.consumed_at is not None
            or challenge.expires_at <= timezone.now()
            or challenge.attempts >= MAX_ATTEMPTS
        ):
            raise OtpInvalid("Invalid or expired code")
        if not hmac.compare_digest(challenge.code_hash, hash_code(challenge.id, code or "")):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            invalid = True
    if invalid:
        raise OtpInvalid("Invalid or expired code")
    return challenge


def consume(challenge):
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=["consumed_at"])


def register_failed_attempt(challenge):
    challenge.attempts += 1
    challenge.save(update_fields=["attempts"])


_TEMPLATE_KEYS = {
    OtpChallenge.Purpose.LOGIN: (
        "login_otp_template_name",
        "WHATSAPP_LOGIN_OTP_TEMPLATE_NAME",
        "vms_login",
        "login_otp_template_language",
        "WHATSAPP_LOGIN_OTP_TEMPLATE_LANGUAGE",
    ),
    OtpChallenge.Purpose.PASSWORD_RESET: (
        "password_recovery_template_name",
        "WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_NAME",
        "password_recovery",
        "password_recovery_template_language",
        "WHATSAPP_PASSWORD_RECOVERY_TEMPLATE_LANGUAGE",
    ),
}

_COPY = {
    OtpChallenge.Purpose.LOGIN: (
        "Your Drona Logitech sign-in code",
        "Sign-in code sent (code redacted)",
        "LOGIN_OTP",
    ),
    OtpChallenge.Purpose.PASSWORD_RESET: (
        "Your Drona Logitech password recovery code",
        "Password recovery code sent (code redacted)",
        "PASSWORD_RESET_OTP",
    ),
}


def send_challenge(challenge, code):
    from integrations.services import _whatsapp_template_setting, queue_message

    subject, summary, event_key = _COPY[challenge.purpose]
    minutes = int(CODE_TTL.total_seconds() // 60)
    if challenge.purpose == OtpChallenge.Purpose.LOGIN:
        body = (
            f"OTP Code: {code}. This is your OTP code for {settings.OTP_APP_LABEL}. "
            f"For your security, do not share this code. It expires in {minutes} minutes."
        )
        body_parameters = [code, settings.OTP_APP_LABEL]
    else:
        body = (
            f"{code} is your password recovery code. For your security, do not share this code. "
            f"It expires in {minutes} minutes."
        )
        body_parameters = [code]

    provider_options = {}
    if challenge.channel == OtpChallenge.Channel.WHATSAPP:
        name_key, name_env, name_default, language_key, language_env = _TEMPLATE_KEYS[
            challenge.purpose
        ]
        connection_option = _whatsapp_template_setting(
            f"{challenge.purpose.lower()}_button_type", "WHATSAPP_OTP_BUTTON_TYPE", "none"
        )
        provider_options = {
            "template_name": _whatsapp_template_setting(name_key, name_env, name_default),
            "template_language": _whatsapp_template_setting(language_key, language_env, "en"),
            "body_parameters": body_parameters,
            "otp_button_type": connection_option,
            "otp_button_code": code,
        }
        recipient = challenge.user.whatsapp_phone
        channel = "WHATSAPP"
    else:
        recipient = challenge.user.email
        channel = "EMAIL"

    return queue_message(
        channel=channel,
        recipient=recipient,
        subject=subject,
        body=body,
        summary=summary,
        object_type="account",
        object_id=str(challenge.user_id),
        idempotency_key=f"otp:{challenge.id}",
        user=challenge.user,
        event_key=event_key,
        provider_options=provider_options,
    )
