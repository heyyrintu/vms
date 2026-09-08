import pytest
from rest_framework.test import APIClient

from accounts.models import User
from integrations.models import IntegrationConnection

WHATSAPP_PAYLOAD = {
    "access_token": "token-1",
    "phone_number_id": "1234567890",
    "approval_template_name": "drona_logitech_approval_review",
    "approval_template_language": "en",
    "finance_template_name": "drona_logitech_finance_ready",
    "finance_template_language": "en",
    "operations_approval_template_name": "drona_logitech_operations_approval",
    "operations_approval_template_language": "en",
    "operations_payment_template_name": "drona_logitech_operations_payment",
    "operations_payment_template_language": "en",
    "operations_settlement_template_name": "drona_logitech_operations_settlement",
    "operations_settlement_template_language": "en",
    "login_otp_template_name": "vms_login",
    "login_otp_template_language": "en",
    "password_recovery_template_name": "password_recovery",
    "password_recovery_template_language": "en",
}


def _admin_client(users):
    client = APIClient()
    client.force_authenticate(users[User.Role.ADMIN])
    return client


@pytest.mark.django_db
def test_admin_can_connect_with_a_valid_button_type(users):
    client = _admin_client(users)
    response = client.post(
        "/api/integration-connections/whatsapp/connect/",
        {**WHATSAPP_PAYLOAD, "login_button_type": "url"},
        format="json",
    )
    assert response.status_code == 200
    connection = IntegrationConnection.objects.get(provider=IntegrationConnection.Provider.WHATSAPP)
    assert connection.configuration["login_button_type"] == "url"


@pytest.mark.django_db
def test_an_invalid_button_type_is_rejected(users):
    client = _admin_client(users)
    response = client.post(
        "/api/integration-connections/whatsapp/connect/",
        {**WHATSAPP_PAYLOAD, "login_button_type": "not-a-real-type"},
        format="json",
    )
    assert response.status_code == 400
    assert not IntegrationConnection.objects.filter(
        provider=IntegrationConnection.Provider.WHATSAPP
    ).exists()


@pytest.mark.django_db
def test_omitting_the_button_type_on_a_later_connect_preserves_the_stored_value(users):
    client = _admin_client(users)
    first = client.post(
        "/api/integration-connections/whatsapp/connect/",
        {**WHATSAPP_PAYLOAD, "login_button_type": "url"},
        format="json",
    )
    assert first.status_code == 200

    second = client.post(
        "/api/integration-connections/whatsapp/connect/",
        WHATSAPP_PAYLOAD,
        format="json",
    )
    assert second.status_code == 200
    connection = IntegrationConnection.objects.get(provider=IntegrationConnection.Provider.WHATSAPP)
    assert connection.configuration["login_button_type"] == "url"
