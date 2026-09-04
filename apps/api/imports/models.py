from django.conf import settings
from django.db import models

from operations.models import TimeStampedModel


class ImportJob(TimeStampedModel):
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    original_filename = models.CharField(max_length=255)
    status = models.CharField(max_length=20, default="PREVIEWED")
    row_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    source_hash = models.CharField(max_length=64, unique=True)
    summary = models.JSONField(default=dict)
    original_file = models.FileField(upload_to="imports/%Y/%m/", blank=True)
    result = models.JSONField(default=dict, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
