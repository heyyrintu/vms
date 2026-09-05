import hashlib
import json

from django.conf import settings
from django.db import models, transaction


class AuditLog(models.Model):
    class Source(models.TextChoices):
        UI = "UI", "UI"
        API = "API", "API"
        IMPORT = "IMPORT", "Import"
        INTEGRATION = "INTEGRATION", "Integration"
        SYSTEM = "SYSTEM", "System"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=80)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.API)
    previous_hash = models.CharField(max_length=64, blank=True)
    entry_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["object_type", "object_id", "-created_at"])]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Audit logs are append-only")
        # Persist the same JSON-safe values that are hashed, including dates/Decimals.
        self.before = json.loads(json.dumps(self.before, default=str))
        self.after = json.loads(json.dumps(self.after, default=str))
        with transaction.atomic():
            previous = AuditLog.objects.select_for_update().order_by("-id").first()
            self.previous_hash = previous.entry_hash if previous else ""
            payload = json.dumps(
                {
                    "actor": self.actor_id,
                    "action": self.action,
                    "object_type": self.object_type,
                    "object_id": self.object_id,
                    "before": self.before,
                    "after": self.after,
                    "request_id": self.request_id,
                    "source": self.source,
                    "previous_hash": self.previous_hash,
                },
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            )
            self.entry_hash = hashlib.sha256(payload.encode()).hexdigest()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit logs cannot be deleted")


def record_audit(*, actor, action, instance, before=None, after=None, request_id="", source="API"):
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        object_type=instance._meta.label,
        object_id=str(instance.pk),
        before=before or {},
        after=after or {},
        request_id=request_id,
        source=source,
    )
