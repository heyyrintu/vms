from rest_framework.permissions import BasePermission

from .models import User

ROLE_CAPABILITIES = {
    User.Role.OPERATIONS: {"masters.read", "masters.write", "trips.read", "trips.write", "approvals.read", "approvals.request", "payments.read", "comments.write", "ledgers.read"},
    User.Role.APPROVER: {"masters.read", "trips.read", "approvals.read", "approvals.decide", "comments.write", "ledgers.read"},
    User.Role.FINANCE: {"masters.read", "trips.read", "approvals.read", "payments.write", "payments.read", "comments.write", "ledgers.read", "reports.read", "sensitive.read"},
    User.Role.MANAGEMENT: {"masters.read", "trips.read", "approvals.read", "payments.read", "comments.write", "ledgers.read", "reports.read", "sensitive.read"},
    User.Role.TRANSPORTER: {"own.read", "masters.read", "trips.read", "payments.read", "ledgers.read"},
    User.Role.ADMIN: {"*"},
}


def has_capability(user, capability):
    if not user or not user.is_authenticated:
        return False
    capabilities = ROLE_CAPABILITIES.get(user.role, set())
    return "*" in capabilities or capability in capabilities


class HasCapability(BasePermission):
    capability = None

    def has_permission(self, request, view):
        return has_capability(request.user, self.capability or getattr(view, "required_capability", ""))


class RolePermission(BasePermission):
    read_capability = None
    write_capability = None

    def has_permission(self, request, view):
        capability = self.read_capability if request.method in {"GET", "HEAD", "OPTIONS"} else self.write_capability
        return has_capability(request.user, capability)
