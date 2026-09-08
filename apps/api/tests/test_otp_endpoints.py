import pytest
from rest_framework.test import APIClient

from accounts import otp
from accounts.models import OtpChallenge, User
from core.crypto import encrypt_value


@pytest.fixture(autouse=True)
def _clear_throttle_history():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member",
        password="StrongPass123!",
        email="member@drona.test",
        whatsapp_phone="919811111111",
    )


def request_code(client, identifier, purpose="LOGIN"):
    return client.post(
        "/api/auth/otp/request/",
        {"identifier": identifier, "purpose": purpose},
        format="json",
    )


@pytest.mark.django_db
def test_login_with_an_emailed_code(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "member@drona.test")
    assert response.status_code == 200
    assert response.data["channel"] == "EMAIL"
    assert response.data["destination_masked"] == "m***@drona.test"

    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)
    verify = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": response.data["challenge_id"], "code": code},
        format="json",
    )
    assert verify.status_code == 200
    assert verify.data["username"] == "member"
    assert client.get("/api/auth/me/").status_code == 200


def _code_for(challenge):
    """Brute-force the six-digit space; only test code may do this."""
    for candidate in range(1_000_000):
        value = f"{candidate:06d}"
        if otp.hash_code(challenge.id, value) == challenge.code_hash:
            return value
    raise AssertionError("code not found")


@pytest.mark.django_db
def test_login_verify_rejects_a_deactivated_user(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "member@drona.test")
    assert response.status_code == 200

    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)

    member.is_active = False
    member.save(update_fields=["is_active"])

    verify = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": response.data["challenge_id"], "code": code},
        format="json",
    )
    assert verify.status_code == 400
    assert verify.data["detail"] == "Invalid or expired code"
    assert client.get("/api/auth/me/").status_code != 200


@pytest.mark.django_db
def test_password_reset_verify_rejects_a_deactivated_user(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "member@drona.test", purpose="PASSWORD_RESET")
    assert response.status_code == 200

    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)

    member.is_active = False
    member.save(update_fields=["is_active"])

    verify = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": response.data["challenge_id"],
            "code": code,
            "purpose": "PASSWORD_RESET",
        },
        format="json",
    )
    assert verify.status_code == 400
    assert verify.data["detail"] == "Invalid or expired code"
    assert "reset_ticket" not in verify.data


@pytest.mark.django_db
def test_unknown_identifier_is_indistinguishable(settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "nobody@drona.test")
    assert response.status_code == 200
    assert set(response.data) == {"challenge_id", "channel", "destination_masked", "expires_in"}
    assert OtpChallenge.objects.count() == 0
    verify = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": response.data["challenge_id"], "code": "123456"},
        format="json",
    )
    assert verify.status_code == 400
    assert verify.data["detail"] == "Invalid or expired code"


@pytest.mark.django_db
def test_mfa_user_must_supply_the_authenticator_code(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    from accounts.mfa import generate_secret

    secret = generate_secret()
    member.mfa_secret_encrypted = encrypt_value(secret)
    member.mfa_enabled = True
    member.save(update_fields=["mfa_secret_encrypted", "mfa_enabled"])

    client = APIClient()
    requested = request_code(client, "member@drona.test")
    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)

    refused = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": requested.data["challenge_id"], "code": code},
        format="json",
    )
    assert refused.status_code == 400
    assert refused.data["mfa_required"] is True
    challenge.refresh_from_db()
    assert challenge.consumed_at is None
    assert challenge.attempts == 1

    import time

    from accounts.mfa import _code as totp

    accepted = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": requested.data["challenge_id"],
            "code": code,
            "otp": totp(secret, int(time.time()) // 30),
        },
        format="json",
    )
    assert accepted.status_code == 200
    challenge.refresh_from_db()
    assert challenge.consumed_at is not None


@pytest.mark.django_db
def test_resend_cooldown_returns_429(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    assert request_code(client, "member@drona.test").status_code == 200
    assert request_code(client, "member@drona.test").status_code == 429


@pytest.mark.django_db
def test_verify_with_a_non_uuid_challenge_id_returns_400_not_500():
    client = APIClient()
    response = client.post(
        "/api/auth/otp/verify/",
        {"challenge_id": "abc", "code": "123456"},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["detail"] == "Invalid or expired code"


@pytest.mark.django_db
def test_password_reset_challenge_cannot_be_redeemed_as_login(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "member@drona.test", purpose="PASSWORD_RESET")
    assert response.status_code == 200

    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)

    verify = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": response.data["challenge_id"],
            "code": code,
            "purpose": "LOGIN",
        },
        format="json",
    )
    assert verify.status_code == 400
    assert verify.data["detail"] == "Invalid or expired code"
    assert client.get("/api/auth/me/").status_code != 200


@pytest.mark.django_db
def test_login_challenge_cannot_be_redeemed_as_password_reset(member, settings):
    settings.INTEGRATION_DELIVERY_MODE = "async"
    client = APIClient()
    response = request_code(client, "member@drona.test", purpose="LOGIN")
    assert response.status_code == 200

    challenge = OtpChallenge.objects.get(user=member)
    code = _code_for(challenge)

    verify = client.post(
        "/api/auth/otp/verify/",
        {
            "challenge_id": response.data["challenge_id"],
            "code": code,
            "purpose": "PASSWORD_RESET",
        },
        format="json",
    )
    assert verify.status_code == 400
    assert "reset_ticket" not in verify.data


@pytest.mark.django_db
def test_session_creating_views_reject_a_request_without_a_csrf_token(member, settings):
    """A cross-origin form must not be able to log a victim into another account.

    APIView.as_view() is wrapped in csrf_exempt, and DRF's SessionAuthentication
    only enforces CSRF once a session already authenticates the request — so an
    AllowAny view that calls login() is unprotected unless it opts back in.
    """
    settings.INTEGRATION_DELIVERY_MODE = "async"
    csrf_client = APIClient(enforce_csrf_checks=True)

    refused = csrf_client.post(
        "/api/auth/otp/request/",
        {"identifier": "member@drona.test", "purpose": "LOGIN"},
        format="json",
    )
    assert refused.status_code == 403
    assert OtpChallenge.objects.count() == 0

    refused_login = csrf_client.post(
        "/api/auth/login/",
        {"username": "member", "password": "StrongPass123!"},
        format="json",
    )
    assert refused_login.status_code == 403
    assert csrf_client.get("/api/auth/me/").status_code != 200

    # The same client succeeds once it carries the token the CSRF endpoint hands out.
    csrf_client.get("/api/auth/csrf/")
    token = csrf_client.cookies["csrftoken"].value
    allowed = csrf_client.post(
        "/api/auth/otp/request/",
        {"identifier": "member@drona.test", "purpose": "LOGIN"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert allowed.status_code == 200
    assert OtpChallenge.objects.count() == 1
