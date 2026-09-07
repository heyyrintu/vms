import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
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


def issue_challenge(user, *, purpose, channel, request=None):
    now = timezone.now()
    recent = OtpChallenge.objects.filter(
        user=user, purpose=purpose, created_at__gte=now - timedelta(hours=1)
    )
    if recent.filter(created_at__gt=now - RESEND_COOLDOWN).exists():
        raise OtpRateLimited("A code was sent moments ago")
    if recent.count() >= MAX_PER_HOUR:
        raise OtpRateLimited("Too many codes requested in the last hour")

    OtpChallenge.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(
        consumed_at=now
    )
    destination = user.email if channel == OtpChallenge.Channel.EMAIL else user.whatsapp_phone
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = OtpChallenge(
        user=user,
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
        except (OtpChallenge.DoesNotExist, ValueError, TypeError):
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
