import json

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from core.crypto import decrypt_value
from integrations.models import IntegrationConnection, IntegrationMessage
from integrations.providers import SMTPProvider
from integrations.services import queue_message


class FakeSMTPClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.message = None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, *, context):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.calls.append("send_message")
        self.message = message


def test_smtp_provider_sends_with_starttls_and_message_id(monkeypatch):
    FakeSMTPClient.instances.clear()
    monkeypatch.setattr("integrations.providers.smtplib.SMTP", FakeSMTPClient)
    provider = SMTPProvider(
        host="smtp.example.test",
        port=587,
        username="mailer",
        password="secret",
        from_email="transport@example.test",
        use_tls=True,
    )

    result = provider.send(
        recipient="vendor@example.test",
        subject="Payment complete",
        body="Payment PAY-1 has been recorded.",
        idempotency_key="payment-email:1",
    )

    client = FakeSMTPClient.instances[0]
    assert client.kwargs == {"host": "smtp.example.test", "port": 587, "timeout": 20}
    assert client.calls == [
        "ehlo",
        "starttls",
        "ehlo",
        ("login", "mailer", "secret"),
        "send_message",
    ]
    assert client.message["From"] == "transport@example.test"
    assert client.message["X-Drona-Idempotency-Key"] == "payment-email:1"
    assert result.message_id
    assert result.status == "SENT"


@pytest.mark.django_db(transaction=True)
def test_sync_delivery_mode_sends_after_database_commit(monkeypatch, settings, users):
    settings.INTEGRATION_DELIVERY_MODE = "sync"
    monkeypatch.setenv("EMAIL_PROVIDER", "fake")

    message = queue_message(
        channel=IntegrationMessage.Channel.EMAIL,
        recipient="approver@example.test",
        subject="Approval requested",
        body="Approval PA-1 needs a decision.",
        object_type="approval",
        object_id="1",
        idempotency_key="sync-email-test-1",
        event_key="APPROVAL_REQUESTED",
        actor=users[User.Role.ADMIN],
    )

    message.refresh_from_db()
    assert message.status == "SENT"
    assert message.external_message_id.startswith("fake-email-")


@pytest.mark.django_db
def test_admin_can_save_encrypted_smtp_connection(users):
    client = APIClient()
    client.force_authenticate(users[User.Role.ADMIN])
    response = client.post(
        "/api/integration-connections/smtp/connect/",
        {
            "host": "smtp.example.test",
            "port": 465,
            "username": "mailer",
            "password": "smtp-password",
            "from_email": "transport@example.test",
            "use_tls": False,
            "use_ssl": True,
            "timeout": 30,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["provider"] == "SMTP"
    assert "encrypted_credentials" not in response.data
    connection = IntegrationConnection.objects.get(provider=IntegrationConnection.Provider.SMTP)
    credentials = json.loads(decrypt_value(connection.encrypted_credentials))
    assert credentials["password"] == "smtp-password"
    assert connection.configuration == {
        "host": "smtp.example.test",
        "port": 465,
        "from_email": "transport@example.test",
        "security": "SSL",
    }
