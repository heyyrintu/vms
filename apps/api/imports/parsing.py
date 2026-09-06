"""Cell parsing shared by the legacy, indent and MIS importers."""

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from openpyxl.utils.datetime import from_excel

DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


def parse_text(value):
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_decimal(value, field, errors, *, places="0.01", required=True, default=None):
    """Quantize a cell to ``places``; blanks return ``default`` (and record an error when required)."""
    if value in (None, ""):
        if required:
            errors.append(f"{field} is required")
        return default
    try:
        return Decimal(str(value)).quantize(Decimal(places))
    except (InvalidOperation, ValueError):
        errors.append(f"{field} must be numeric")
        return None


def parse_datetime(value, field, errors, epoch, *, required=False, invalid_message="is not a valid date/time"):
    if value in (None, ""):
        if required:
            errors.append(f"{field} is required")
        return None
    parsed = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, int | float):
        try:
            converted = from_excel(value, epoch)
            if isinstance(converted, datetime):
                parsed = converted
            elif isinstance(converted, date):
                parsed = datetime.combine(converted, time.min)
            else:
                # Serials between 0 and 1 are times of day, which no importer column accepts.
                parsed = None
        except (ValueError, OverflowError):
            parsed = None
    elif isinstance(value, str):
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(value.strip(), fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        errors.append(f"{field} {invalid_message}")
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def parse_date(value, field, errors, epoch, *, required=False, invalid_message="is not a valid date"):
    parsed = parse_datetime(value, field, errors, epoch, required=required, invalid_message=invalid_message)
    return parsed.date() if parsed else None
