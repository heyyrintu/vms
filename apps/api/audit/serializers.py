from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = "__all__"

    @extend_schema_field(serializers.CharField())
    def get_actor_name(self, obj):
        if not obj.actor:
            return "System"
        return obj.actor.get_full_name() or obj.actor.username
