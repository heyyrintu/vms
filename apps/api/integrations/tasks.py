from celery import shared_task
from django.utils import timezone

from .models import IntegrationMessage
from .services import deliver_message


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def deliver_message_task(message_id, actor_id=None):
    from accounts.models import User

    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    return deliver_message(message_id, actor=actor).pk


@shared_task
def retry_failed_messages():
    due = IntegrationMessage.objects.filter(
        status__in=["QUEUED", "FAILED"],
        channel__in=["EMAIL", "WHATSAPP"],
    ).filter(next_retry_at__isnull=True) | IntegrationMessage.objects.filter(
        status="FAILED", next_retry_at__lte=timezone.now()
    )
    queued = 0
    for message_id in due.values_list("id", flat=True)[:200]:
        deliver_message_task.delay(message_id)
        queued += 1
    return {"queued": queued}
