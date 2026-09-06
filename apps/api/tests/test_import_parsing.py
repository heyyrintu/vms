from datetime import date, datetime
from decimal import Decimal

from openpyxl.utils.datetime import CALENDAR_WINDOWS_1900

from imports.parsing import parse_date, parse_datetime, parse_decimal, parse_text


def test_parse_text_normalises_numbers_and_whitespace():
    assert parse_text(None) == ""
    assert parse_text(12.0) == "12"
    assert parse_text("  HR10 ") == "HR10"


def test_parse_decimal_reports_errors_instead_of_raising():
    errors = []
    assert parse_decimal("12.345", "RATE", errors, places="0.001") == Decimal("12.345")
    assert parse_decimal("abc", "RATE", errors) is None
    assert parse_decimal(None, "RATE", errors) is None
    assert parse_decimal(None, "RATE", errors, required=False, default=Decimal("0.00")) == Decimal("0.00")
    assert errors == ["RATE must be numeric", "RATE is required"]


def test_parse_date_accepts_excel_serials_and_strings():
    errors = []
    assert parse_date(45500, "DATE", errors, CALENDAR_WINDOWS_1900) == date(2024, 7, 27)
    assert parse_date("27/07/2024", "DATE", errors, CALENDAR_WINDOWS_1900) == date(2024, 7, 27)
    parsed = parse_datetime("2024-07-27 10:30", "AT", errors, CALENDAR_WINDOWS_1900)
    assert parsed.replace(tzinfo=None) == datetime(2024, 7, 27, 10, 30)
    assert parse_date("not a date", "DATE", errors, CALENDAR_WINDOWS_1900) is None
    assert errors == ["DATE is not a valid date"]
