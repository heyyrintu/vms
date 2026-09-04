from rest_framework import serializers

from .models import OrganizationSettings


class OrganizationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationSettings
        fields = "__all__"
        read_only_fields = ["id", "updated_at"]

