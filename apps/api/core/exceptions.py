from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Translate service-layer domain errors into stable API responses."""
    if isinstance(exc, DjangoValidationError):
        exc = ValidationError(exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages})
    elif isinstance(exc, PermissionError):
        exc = PermissionDenied(str(exc))
    elif isinstance(exc, ValueError):
        exc = ValidationError({"detail": str(exc)})
    elif isinstance(exc, ObjectDoesNotExist):
        exc = NotFound(str(exc) or "The requested resource was not found")
    return exception_handler(exc, context)
