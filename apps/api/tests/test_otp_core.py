from datetime import timedelta

import pytest
from django.utils import timezone

from accounts import otp
from accounts.models import OtpChallenge, User


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member", email="member@drona.test", whatsapp_phone="919811111111"
    )


@pytest.mark.django_db
def test_issue_returns_six_digit_code_that_is_never_stored(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    assert len(code) == 6 and code.isdigit()
    assert code not in challenge.code_hash
    assert challenge.code_hash != code
    assert challenge.expires_at > timezone.now()


@pytest.mark.django_db
def test_verify_accepts_the_issued_code_without_consuming_it(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    verified = otp.verify_challenge(challenge.id, code, purpose=OtpChallenge.Purpose.LOGIN)
    assert verified.pk == challenge.pk
    assert verified.consumed_at is None


@pytest.mark.django_db
def test_wrong_code_increments_attempts_then_locks_out(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(otp.MAX_ATTEMPTS):
        with pytest.raises(otp.OtpInvalid):
            otp.verify_challenge(challenge.id, wrong, purpose=OtpChallenge.Purpose.LOGIN)
    challenge.refresh_from_db()
    assert challenge.attempts == otp.MAX_ATTEMPTS
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(challenge.id, code, purpose=OtpChallenge.Purpose.LOGIN)


@pytest.mark.django_db
def test_consumed_and_expired_challenges_are_rejected(member):
    challenge, code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    otp.consume(challenge)
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(challenge.id, code, purpose=OtpChallenge.Purpose.LOGIN)

    stale, stale_code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.PASSWORD_RESET, channel=OtpChallenge.Channel.EMAIL
    )
    OtpChallenge.objects.filter(pk=stale.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(stale.id, stale_code, purpose=OtpChallenge.Purpose.PASSWORD_RESET)


@pytest.mark.django_db
def test_issuing_again_supersedes_the_previous_code(member):
    first, first_code = otp.issue_challenge(
        member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
    )
    OtpChallenge.objects.filter(pk=first.pk).update(
        created_at=timezone.now() - otp.RESEND_COOLDOWN - timedelta(seconds=1)
    )
    otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)
    with pytest.raises(otp.OtpInvalid):
        otp.verify_challenge(first.id, first_code, purpose=OtpChallenge.Purpose.LOGIN)


@pytest.mark.django_db
def test_resend_cooldown_and_hourly_cap_raise_rate_limited(member):
    otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)
    with pytest.raises(otp.OtpRateLimited):
        otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)

    # Age every existing challenge for this user past the resend cooldown so the
    # cap loop below is only ever blocked by the hourly cap, never the cooldown.
    # created_at uses auto_now_add, so it can only be rewritten via a queryset
    # .update() — never by assigning the attribute and calling .save().
    OtpChallenge.objects.filter(user=member).update(
        created_at=timezone.now() - otp.RESEND_COOLDOWN - timedelta(seconds=1)
    )

    aged = timezone.now() - otp.RESEND_COOLDOWN - timedelta(seconds=1)
    for _ in range(otp.MAX_PER_HOUR - 1):
        challenge, _ = otp.issue_challenge(
            member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL
        )
        OtpChallenge.objects.filter(pk=challenge.pk).update(created_at=aged)
    with pytest.raises(otp.OtpRateLimited):
        otp.issue_challenge(member, purpose=OtpChallenge.Purpose.LOGIN, channel=OtpChallenge.Channel.EMAIL)


@pytest.mark.django_db
def test_resolve_identifier_matches_email_and_phone_and_skips_inactive(member):
    assert otp.resolve_identifier("MEMBER@drona.test") == (member, OtpChallenge.Channel.EMAIL)
    assert otp.resolve_identifier("+91 98111 11111") == (member, OtpChallenge.Channel.WHATSAPP)
    assert otp.resolve_identifier("nobody@drona.test") == (None, OtpChallenge.Channel.EMAIL)
    member.is_active = False
    member.save(update_fields=["is_active"])
    assert otp.resolve_identifier("member@drona.test") == (None, OtpChallenge.Channel.EMAIL)


def test_mask_destination_hides_most_of_the_identifier():
    assert otp.mask_destination("rintu.m@dronalogitech.com") == "r***@dronalogitech.com"
    assert otp.mask_destination("918777430172") == "+91 87****0172"
