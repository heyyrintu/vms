from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    readonly_fields = [field.name for field in AuditLog._meta.fields]
    list_display = ["created_at", "action", "object_type", "object_id", "actor"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

