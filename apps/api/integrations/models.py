from django.conf import settings
from django.db import models

from operations.models import TimeStampedModel, Vendor


class IntegrationConnection(TimeStampedModel):
    class Provider(models.TextChoices):
        SMTP = "SMTP", "SMTP email"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    provider = models.CharField(max_length=20, choices=Provider.choices, unique=True)
    status = models.CharField(max_length=20, default="DISCONNECTED")
    account_label = models.CharField(max_length=150, blank=True)
    encrypted_credentials = models.TextField(blank=True)
    configuration = models.JSONField(default=dict, blank=True)
    watch_expires_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)


class IntegrationMessage(TimeStampedModel):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        WHATSAPP = "WHATSAPP", "WhatsApp"
        IN_APP = "IN_APP", "In app"

    channel = models.CharField(max_length=20, choices=Channel.choices)
    direction = models.CharField(max_length=10, choices=[("OUTBOUND", "Outbound"), ("INBOUND", "Inbound")])
    idempotency_key = models.CharField(max_length=180, unique=True)
    external_message_id = models.CharField(max_length=180, blank=True, db_index=True)
    external_thread_id = models.CharField(max_length=180, blank=True, db_index=True)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=80)
    vendor = models.ForeignKey(Vendor, null=True, blank=True, on_delete=models.PROTECT, related_name="integration_messages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    recipient = models.CharField(max_length=180, blank=True)
    template_id = models.CharField(max_length=100, blank=True)
    subject = models.CharField(max_length=240, blank=True)
    body_summary = models.TextField(blank=True)
    payload_encrypted = models.TextField(blank=True)
    status = models.CharField(max_length=20, default="QUEUED")
    raw_metadata = models.JSONField(default=dict, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    event_key = models.CharField(max_length=80, blank=True, db_index=True)
    last_error = models.TextField(blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)


class UnmappedInboundMessage(TimeStampedModel):
    message = models.OneToOneField(IntegrationMessage, on_delete=models.PROTECT)
    reason = models.CharField(max_length=240)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT)
    resolved_at = models.DateTimeField(null=True, blank=True)


class NotificationTemplate(TimeStampedModel):
    event_key = models.CharField(max_length=80)
    channel = models.CharField(max_length=20, choices=IntegrationMessage.Channel.choices)
    subject_template = models.CharField(max_length=240, blank=True)
    body_template = models.TextField()
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event_key", "channel"], name="unique_notification_event_channel")
        ]
        ordering = ["event_key", "channel"]


class NotificationPreference(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    event_key = models.CharField(max_length=80)
    channel = models.CharField(max_length=20, choices=IntegrationMessage.Channel.choices)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event_key", "channel"], name="unique_user_event_channel")
        ]
