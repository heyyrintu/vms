import pytest
from django.core.signing import TimestampSigner
from rest_framework.test import APIClient

from accounts import otp
from accounts.models import OtpChallenge, User
from tests.test_otp_endpoints import _code_for


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member", password="StrongPass123!", email="member@drona.test"
    )


@pytest.mark.django_db
def test_password_is_reset_with_a_delivered_code(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    requested = client.post(
        "/api/auth/otp/request/",
        {"identifier": "member@drona.test", "purpose": "PASSWORD_RESET"},
        format="json",
    )
    challenge = OtpChallenge.objects.get(user=member)
    verified = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": requested.data["challenge_id"],
            "code": _code_for(challenge),
            "purpose": "PASSWORD_RESET",
        },
        format="json",
    )
    assert verified.status_code == 200

    confirmed = client.post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": verified.data["reset_ticket"], "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert confirmed.status_code == 200
    member.refresh_from_db()
    assert member.check_password("BrandNewPass456!")


@pytest.mark.django_db
def test_forged_ticket_is_rejected(member):
    client = APIClient()
    forged = TimestampSigner().sign_object({"user": member.pk, "challenge": "not-a-challenge"})
    response = client.post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": forged, "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert response.status_code == 400
    member.refresh_from_db()
    assert member.check_password("StrongPass123!")


@pytest.mark.django_db
def test_ticket_for_an_unconsumed_challenge_is_rejected(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    challenge, _ = otp.issue_challenge(
        member,
        purpose=OtpChallenge.Purpose.PASSWORD_RESET,
        channel=OtpChallenge.Channel.EMAIL,
    )
    ticket = TimestampSigner().sign_object({"user": member.pk, "challenge": str(challenge.id)})
    response = APIClient().post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": ticket, "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_expired_ticket_is_rejected(member, settings, monkeypatch):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    challenge, _ = otp.issue_challenge(
        member,
        purpose=OtpChallenge.Purpose.PASSWORD_RESET,
        channel=OtpChallenge.Channel.EMAIL,
    )
    otp.consume(challenge)
    ticket = TimestampSigner().sign_object({"user": member.pk, "challenge": str(challenge.id)})
    monkeypatch.setattr("accounts.otp.RESET_TICKET_MAX_AGE", -1)
    response = APIClient().post(
        "/api/auth/password/reset/confirm/",
        {"reset_ticket": ticket, "new_password": "BrandNewPass456!"},
        format="json",
    )
    assert response.status_code == 400
    member.refresh_from_db()
    assert member.check_password("StrongPass123!")


@pytest.mark.django_db
def test_the_magic_link_endpoint_is_gone():
    response = APIClient().post(
        "/api/auth/password/reset/", {"email": "member@drona.test"}, format="json"
    )
    assert response.status_code == 404
