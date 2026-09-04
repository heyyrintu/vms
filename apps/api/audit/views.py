from rest_framework import viewsets

from accounts.models import User

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        if getattr(self.request.user, "role", "") not in {
            User.Role.ADMIN,
            User.Role.MANAGEMENT,
            User.Role.APPROVER,
        }:
            return AuditLog.objects.none()
        queryset = AuditLog.objects.select_related("actor")
        object_type = self.request.query_params.get("object_type")
        object_id = self.request.query_params.get("object_id")
        if object_type:
            queryset = queryset.filter(object_type=object_type)
        if object_id:
            queryset = queryset.filter(object_id=object_id)
        return queryset
