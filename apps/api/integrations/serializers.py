from rest_framework import serializers

from .models import (
    IntegrationConnection,
    IntegrationMessage,
    NotificationPreference,
    NotificationTemplate,
    UnmappedInboundMessage,
)


class IntegrationConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationConnection
        exclude = ["encrypted_credentials"]


class IntegrationMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationMessage
        exclude = ["payload_encrypted"]


class NotificationTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields = "__all__"


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = "__all__"
        read_only_fields = ["user"]


class UnmappedInboundSerializer(serializers.ModelSerializer):
    message_detail = IntegrationMessageSerializer(source="message", read_only=True)

    class Meta:
        model = UnmappedInboundMessage
        fields = "__all__"
        read_only_fields = ["resolved_by", "resolved_at"]
