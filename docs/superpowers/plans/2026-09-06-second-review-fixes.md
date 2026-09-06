# Second Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every finding from the 2026-09-06 second-pass review of the VMS codebase: report correctness and query cost, importer robustness, webhook hardening, session hygiene, and the frontend register gaps.

**Architecture:** Backend fixes stay inside the existing Django apps (`payments`, `imports`, `integrations`, `accounts`) and follow the service-function style already used there. Reports move from per-trip aggregates to annotated querysets built once per request. Frontend changes add one shared filter hook and reuse the existing `Pagination` component; no new libraries.

**Tech Stack:** Django 5.2, DRF 3.18, pytest-django, Next.js 16, React 19, TanStack Query 5, Playwright.

**Spec:** The review findings in this conversation (2026-09-06, "second pass"). Two findings were withdrawn after re-reading the code: report totals are already computed over the full row set before paging, and `FIELD_ENCRYPTION_KEY` is already required when `DJANGO_DEBUG=false`.

## Global Constraints

- Python 3.12, run everything with `apps/api/.venv/Scripts/python` on Windows (or `.venv/bin/python` on Linux).
- `ruff check .` must stay clean; CI runs it before tests.
- Every backend task ends with the full suite green: `python -m pytest -q -p no:cacheprovider -p no:warnings` from `apps/api`.
- Frontend tasks end with `npm run lint && npm run typecheck && npm run build` from `apps/web`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Work on a branch off `main` named `fix/second-review`; open one PR at the end.
- Test helpers available in `apps/api/tests/conftest.py`: fixtures `users` (dict keyed by `User.Role`) and `trip_factory(index=1)`. Helpers in `tests/test_lifecycle_regressions.py`: `client_for(user)`, `approval(trip, users, approve=True)`, `payment(item, users, net=None, tds=None, reference=...)`.

---

### Task 1: Report queries built once per request

**Files:**
- Modify: `apps/api/payments/reports.py:44-55` (`_filtered_trips`), `:208-225` (`_trip_financial_row`), `:228-272` (`_vendor_report`)
- Test: `apps/api/tests/test_reports.py` (create)

**Interfaces:**
- Produces: `annotate_financials(trips: QuerySet[Trip]) -> QuerySet[Trip]` adding `approved_gross_total`, `cash_paid_total`, `tds_paid_total` (Decimal, never None). `_trip_financial_row(trip)` now requires an annotated trip. Task 2 reuses `annotate_financials` and `_money_subquery`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_reports.py
from decimal import Decimal

import pytest

from accounts.models import User
from payments.reports import build_report
from tests.test_lifecycle_regressions import approval, payment


@pytest.mark.django_db
def test_trip_cost_report_uses_one_query_per_request_not_per_trip(trip_factory, users, django_assert_max_num_queries):
    for index in range(1, 6):
        batch = approval(trip_factory(index), users)
        payment(batch.items.get(), users, reference=f"UTR-{index}")
    with django_assert_max_num_queries(6):
        report = build_report("trip-cost-payment", {})
    assert len(report.rows) == 5
    row = report.rows[0]
    assert row["cash_paid"] > 0
    assert row["remaining"] == Decimal("0.00")


@pytest.mark.django_db
def test_vendor_aging_counts_only_unpaid_items(trip_factory, users):
    paid_batch = approval(trip_factory(1), users)
    payment(paid_batch.items.get(), users, reference="UTR-PAID")
    approval(trip_factory(2), users)  # approved, never paid
    report = build_report("vendor-aging", {})
    by_vendor = {row["vendor"]: row for row in report.rows}
    paid_vendor = paid_batch.items.get().vendor.display_name
    assert by_vendor[paid_vendor]["unresolved"] == Decimal("0")
    assert by_vendor[paid_vendor]["oldest_unresolved_days"] == 0
    unpaid_rows = [row for name, row in by_vendor.items() if name != paid_vendor]
    assert unpaid_rows and unpaid_rows[0]["unresolved"] > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_reports.py -q -p no:cacheprovider`
Expected: FAIL. The first test exceeds 6 queries; the second reports `oldest_unresolved_days > 0` for the paid vendor.

- [ ] **Step 3: Replace the per-trip aggregates with annotations**

Replace the imports at the top of `apps/api/payments/reports.py`:

```python
from django.db.models import DecimalField, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
```

Add after `_filtered_trips`:

```python
MONEY = DecimalField(max_digits=14, decimal_places=2)


def _money_subquery(queryset, group_field, sum_field):
    """Sum ``sum_field`` for the rows of ``queryset`` that belong to the outer row."""
    totals = queryset.order_by().values(group_field).annotate(total=Sum(sum_field)).values("total")[:1]
    return Coalesce(Subquery(totals, output_field=MONEY), Value(Decimal("0")), output_field=MONEY)


def annotate_financials(trips):
    approved = PaymentApprovalItem.objects.filter(
        trip=OuterRef("pk"), item_status=PaymentApprovalItem.Status.APPROVED
    )
    paid = PaymentAllocation.objects.filter(
        trip=OuterRef("pk"), payment__status=FinancePaymentTransaction.Status.PAID
    )
    return trips.select_related("final_settlement").annotate(
        approved_gross_total=_money_subquery(approved, "trip", "gross_requested"),
        cash_paid_total=_money_subquery(paid, "trip", "net_cash_allocated"),
        tds_paid_total=_money_subquery(paid, "trip", "tds_allocated"),
    )
```

Change `_filtered_trips` to return `annotate_financials(queryset)` instead of `queryset`.

Replace `_trip_financial_row`:

```python
def _trip_financial_row(trip):
    settlement = getattr(trip, "final_settlement", None)
    return {
        "trip": trip.trip_no,
        "date": trip.deployment_date,
        "vendor": trip.vendor.display_name,
        "status": trip.status,
        "vendor_cost": settlement.total_vendor_gross_cost if settlement else trip.vendor_freight_rate,
        "approved_gross": trip.approved_gross_total,
        "cash_paid": trip.cash_paid_total,
        "tds": trip.tds_paid_total,
        "remaining": trip.approved_gross_total - trip.cash_paid_total - trip.tds_paid_total,
    }
```

Replace `_vendor_report`:

```python
def _vendor_report(slug, trips):
    today = timezone.localdate()
    groups = {}
    for trip in trips.order_by("vendor__display_name", "pk"):
        group = groups.setdefault(
            trip.vendor_id,
            {"vendor": trip.vendor.display_name, "trips": 0, "business": Decimal("0"), "cash_paid": Decimal("0"),
             "tds": Decimal("0"), "unresolved": Decimal("0"), "advance_cash_paid_unsettled": Decimal("0"), "trip_ids": []},
        )
        group["trips"] += 1
        group["business"] += trip.vendor_freight_rate
        group["cash_paid"] += trip.cash_paid_total
        group["tds"] += trip.tds_paid_total
        group["unresolved"] += trip.approved_gross_total - trip.cash_paid_total - trip.tds_paid_total
        if trip.settlement_status != "SETTLED":
            group["advance_cash_paid_unsettled"] += trip.cash_paid_total
        group["trip_ids"].append(trip.pk)
    paid_per_item = PaymentAllocation.objects.filter(
        approval_item=OuterRef("pk"), payment__status=FinancePaymentTransaction.Status.PAID
    )
    rows = []
    for vendor_id, group in groups.items():
        oldest = (
            PaymentApprovalItem.objects.filter(
                vendor_id=vendor_id, trip_id__in=group["trip_ids"], item_status=PaymentApprovalItem.Status.APPROVED
            )
            .annotate(paid_gross_total=_money_subquery(paid_per_item, "approval_item", "gross_amount_allocated"))
            .filter(gross_requested__gt=F("paid_gross_total"))
            .order_by("batch__submitted_at")
            .values_list("batch__submitted_at", flat=True)
            .first()
        )
        row = {key: value for key, value in group.items() if key not in {"trip_ids", "advance_cash_paid_unsettled"}}
        row["oldest_unresolved_days"] = (today - oldest.date()).days if oldest else 0
        if slug == "vendor-advance-outstanding":
            row["advance_cash_paid_unsettled"] = group["advance_cash_paid_unsettled"]
        rows.append(row)
    money_fields = ["business", "cash_paid", "tds", "unresolved"]
    if slug == "vendor-advance-outstanding":
        money_fields.append("advance_cash_paid_unsettled")
    return _with_money_totals(rows, money_fields)
```

Delete the now unused `Vendor` import if ruff reports it.

- [ ] **Step 4: Run the tests and the full suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass, including `tests/test_reports.py`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/payments/reports.py apps/api/tests/test_reports.py
git commit -m "Build report financials with one annotated query and count only unpaid items in vendor aging"
```

---

### Task 2: Profitability report labels provisional rows

**Files:**
- Modify: `apps/api/payments/reports.py:181-205` (the profitability branch at the end of `build_report`)
- Test: `apps/api/tests/test_reports.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_reports.py`:

```python
from payments.models import ClientBilling


@pytest.mark.django_db
def test_profitability_marks_unsettled_trips_as_provisional(trip_factory, users):
    trip = trip_factory(1)
    ClientBilling.objects.create(
        trip=trip, billing_amount=Decimal("60000"), invoice_no="INV-1",
        payment_status="INVOICED", received_amount=Decimal("0"), internal_trip_costs=Decimal("0"),
        created_by=users[User.Role.OPERATIONS],
    )
    report = build_report("profitability", {})
    assert report.rows[0]["basis"] == "PROVISIONAL"
    assert "basis" in report.columns
```

If `ClientBilling.objects.create` rejects a field name, open `apps/api/payments/models.py` around line 232 and match the real field names; the test must create a billing with no settlement.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_reports.py::test_profitability_marks_unsettled_trips_as_provisional -q -p no:cacheprovider`
Expected: FAIL with `KeyError: 'basis'`.

- [ ] **Step 3: Add the basis column**

In the profitability branch of `build_report`, change the appended row to:

```python
        rows.append(
            {
                "trip": trip.trip_no,
                "client": trip.client.name,
                "vendor": trip.vendor.display_name,
                "basis": "SETTLED" if settlement else "PROVISIONAL",
                "billing": billing.billing_amount,
                "vendor_cost": vendor_cost,
                "internal_costs": billing.internal_trip_costs,
                "gross_profit": profit["gross_profit"],
                "margin_percent": profit["margin_percent"],
            }
        )
```

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/payments/reports.py apps/api/tests/test_reports.py
git commit -m "Label provisional vendor cost in the profitability report"
```

---

### Task 3: Legacy Excel importer stops silently truncating and preflights vehicle ownership

**Files:**
- Modify: `apps/api/imports/services.py:89-90` (row cap), `:203-212` (preflight), `:233-240` (vendor lookup)
- Test: `apps/api/tests/test_integrations_import.py`

- [ ] **Step 1: Write the failing tests**

Look at how existing tests in `tests/test_integrations_import.py` build a workbook (the first test uses a helper that writes the 17 legacy columns with `openpyxl`). Reuse that helper name in these tests; call it `legacy_workbook(rows)` below and adjust to the real name.

```python
@pytest.mark.django_db
def test_legacy_preview_rejects_more_than_1000_rows(users):
    from imports.services import preview_workbook
    rows = [sample_row(index) for index in range(1, 1002)]
    with pytest.raises(ValueError, match="1,000"):
        preview_workbook(legacy_workbook(rows))


@pytest.mark.django_db
def test_legacy_confirm_reports_vehicle_owned_by_another_vendor(users):
    from imports.services import confirm_import, preview_workbook
    from operations.models import Vehicle, Vendor
    other = Vendor.objects.create(vendor_code="OTHER", legal_name="Other", display_name="Other Transport")
    Vehicle.objects.create(registration_no="HR10AB1234", vendor=other, vehicle_type="32 FT")
    job = preview_workbook(legacy_workbook([sample_row(1, vehicle="HR10AB1234", vendor="New Transport")]), actor=users[User.Role.OPERATIONS])
    job = confirm_import(job=job, actor=users[User.Role.OPERATIONS], client_id=job.summary["client_id"], create_missing=True)
    assert job.status == "VALIDATION_FAILED"
    assert "another vendor" in job.result["errors"][0]["error"]
```

Match `preview_workbook`, `confirm_import`, `sample_row` and `legacy_workbook` to the real names in `imports/services.py` and the existing test module before running.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_integrations_import.py -q -p no:cacheprovider`
Expected: the first fails because no error is raised; the second fails with a bare `ValueError` from the confirm loop.

- [ ] **Step 3: Implement**

In `imports/services.py` replace:

```python
        if len(rows) >= 1000:
            break
```

with:

```python
        if len(rows) >= 1000:
            raise ValueError("Legacy imports are limited to 1,000 populated rows per workbook")
```

In the preflight loop, after the `vehicle_exists` check, add:

```python
        foreign_vehicle = Vehicle.objects.filter(registration_no=values["vehicle_registration"]).exclude(vendor=vendor).exists() if vendor else False
        if foreign_vehicle:
            preflight_errors.append(
                {"row_no": row["row_no"], "error": f"Vehicle '{values['vehicle_registration']}' belongs to another vendor"}
            )
            continue
```

Replace the vendor `get_or_create` in the confirm loop with an explicit lookup so case-variant duplicates cannot raise `MultipleObjectsReturned`:

```python
        vendor = Vendor.objects.filter(display_name__iexact=values["vendor"]).order_by("pk").first()
        if vendor is None:
            vendor = Vendor.objects.create(
                vendor_code=_vendor_code(values["vendor"]),
                display_name=values["vendor"],
                legal_name=values["vendor"],
            )
```

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/imports/services.py apps/api/tests/test_integrations_import.py
git commit -m "Reject oversized legacy workbooks and preflight vehicle ownership"
```

---

### Task 4: Unmapped-message resolution validates the target object

**Files:**
- Modify: `apps/api/integrations/views.py:226-246` (`UnmappedInboundViewSet.resolve`)
- Test: `apps/api/tests/test_review_fixes.py`

- [ ] **Step 1: Write the failing test**

Append to `apps/api/tests/test_review_fixes.py`:

```python
@pytest.mark.django_db
def test_resolving_an_unmapped_message_requires_an_existing_object(users):
    from integrations.models import IntegrationMessage, UnmappedInboundMessage
    message = IntegrationMessage.objects.create(
        idempotency_key="email-inbound:orphan", channel="EMAIL", direction="INBOUND",
        object_type="unmapped", object_id="", recipient="x@example.test", subject="hi", body_summary="hi", status="RECEIVED",
    )
    item = UnmappedInboundMessage.objects.create(message=message, reason="test")
    response = client_for(users[User.Role.ADMIN]).post(
        f"/api/unmapped-messages/{item.pk}/resolve/", {"object_type": "trip", "object_id": "999999"}, format="json"
    )
    assert response.status_code == 400
    assert not Comment.objects.filter(object_type="trip", object_id="999999").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_review_fixes.py::test_resolving_an_unmapped_message_requires_an_existing_object -q -p no:cacheprovider`
Expected: FAIL, status is 200 and a comment exists.

- [ ] **Step 3: Implement**

In `resolve`, after the `object_type`/`object_id` validation, add:

```python
        from approvals.models import PaymentApprovalBatch
        from operations.models import Trip
        from payments.models import FinancePaymentTransaction

        model = {"approval": PaymentApprovalBatch, "trip": Trip, "payment": FinancePaymentTransaction}[object_type]
        if not object_id.isdigit() or not model.objects.filter(pk=int(object_id)).exists():
            return Response({"detail": f"No {object_type} with id {object_id} exists"}, status=400)
```

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/integrations/views.py apps/api/tests/test_review_fixes.py
git commit -m "Validate the target object before resolving an unmapped inbound message"
```

---

### Task 5: WhatsApp webhook scopes lookups and refuses free-form sends

**Files:**
- Modify: `apps/api/integrations/views.py:318-320`, `:329`; `apps/api/integrations/providers.py:236-243`
- Test: `apps/api/tests/test_review_fixes.py`

- [ ] **Step 1: Write the failing test**

```python
def test_whatsapp_provider_refuses_free_form_messages_without_a_template(monkeypatch):
    from integrations.providers import WhatsAppProvider
    monkeypatch.delenv("WHATSAPP_TEMPLATE_NAME", raising=False)
    provider = WhatsAppProvider(access_token="token", phone_number_id="123")
    with pytest.raises(RuntimeError, match="template"):
        provider.send(recipient="919876543210", subject="x", body="hello", idempotency_key="k")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_review_fixes.py::test_whatsapp_provider_refuses_free_form_messages_without_a_template -q -p no:cacheprovider`
Expected: FAIL. The provider attempts a network call and raises a connection `RuntimeError` whose message does not contain "template".

- [ ] **Step 3: Implement**

In `providers.py` replace the `else:` branch that builds the free-form `text` payload with:

```python
        else:
            raise RuntimeError(
                "WhatsApp requires an approved template name; set WHATSAPP_TEMPLATE_NAME or pass template_name"
            )
```

In `views.py` `_process_cloud_payload`, change the status lookup to:

```python
                    message = IntegrationMessage.objects.filter(
                        channel=IntegrationMessage.Channel.WHATSAPP,
                        external_message_id=status_event.get("id", ""),
                        direction="OUTBOUND",
                    ).first()
```

and the context lookup to:

```python
                    outbound = IntegrationMessage.objects.filter(
                        channel=IntegrationMessage.Channel.WHATSAPP, external_message_id=context_id, direction="OUTBOUND"
                    ).first() if context_id else None
```

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass. If `tests/test_whatsapp_approval.py` fails because it relied on free-form sends, set `WHATSAPP_TEMPLATE_NAME` in that test with `monkeypatch.setenv`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/integrations/views.py apps/api/integrations/providers.py apps/api/tests/test_review_fixes.py
git commit -m "Scope WhatsApp webhook lookups to the channel and require a template for sends"
```

---

### Task 6: Password change keeps the current session and drops the others

**Files:**
- Modify: `apps/api/accounts/views.py:96-108` (`PasswordChangeView.post`), `:146-158` (`PasswordResetConfirmView.post`)
- Test: `apps/api/tests/test_api_security.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_password_change_invalidates_other_sessions(users):
    from django.contrib.sessions.models import Session
    user = users[User.Role.OPERATIONS]
    user.set_password("OldPassword123!"); user.save()
    first, second = APIClient(), APIClient()
    for client in (first, second):
        assert client.post("/api/auth/login/", {"username": user.username, "password": "OldPassword123!"}, format="json").status_code == 200
    response = first.post("/api/auth/password/change/", {"current_password": "OldPassword123!", "new_password": "NewPassword12345!"}, format="json")
    assert response.status_code == 200
    assert first.get("/api/auth/me/").status_code == 200
    assert second.get("/api/auth/me/").status_code == 403
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_api_security.py::test_password_change_invalidates_other_sessions -q -p no:cacheprovider`
Expected: FAIL, the second client still returns 200.

- [ ] **Step 3: Implement**

Add to the imports in `accounts/views.py`:

```python
from django.contrib.auth import update_session_auth_hash
```

Replace `login(request, request.user)` in `PasswordChangeView.post` with:

```python
        update_session_auth_hash(request, request.user)
```

Django's session auth hash is derived from the password, so every other session is invalidated on the next request while this one keeps its cookie. In `PasswordResetConfirmView.post`, nothing changes: no session exists there and the hash rotation already logs out old sessions.

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/accounts/views.py apps/api/tests/test_api_security.py
git commit -m "Rotate the session auth hash on password change so other sessions expire"
```

---

### Task 7: Shared importer parsing helpers

**Files:**
- Create: `apps/api/imports/parsing.py`
- Modify: `apps/api/imports/services.py` (remove `_text`, `_decimal`, `_date`, import them), `apps/api/imports/indents.py:41-100`, `apps/api/imports/mis.py:22,57-62`
- Test: `apps/api/tests/test_import_parsing.py` (create)

**Interfaces:**
- Produces: `parse_text(value) -> str`, `parse_decimal(value, field, errors, *, places="0.01", required=True) -> Decimal | None`, `parse_date(value, field, errors, epoch, *, required=False) -> date | None`, `parse_datetime(value, field, errors, epoch, *, required=False) -> datetime | None`.

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/tests/test_import_parsing.py
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
    assert errors == ["RATE must be numeric", "RATE is required"]


def test_parse_date_accepts_excel_serials_and_strings():
    errors = []
    assert parse_date(45500, "DATE", errors, CALENDAR_WINDOWS_1900) == date(2024, 7, 27)
    assert parse_date("27/07/2024", "DATE", errors, CALENDAR_WINDOWS_1900) == date(2024, 7, 27)
    assert parse_datetime("2024-07-27 10:30", "AT", errors, CALENDAR_WINDOWS_1900).replace(tzinfo=None) == datetime(2024, 7, 27, 10, 30)
    assert errors == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_import_parsing.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: imports.parsing`.

- [ ] **Step 3: Create the module**

```python
# apps/api/imports/parsing.py
"""Cell parsing shared by the legacy, indent and MIS importers."""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from openpyxl.utils.datetime import from_excel

DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


def parse_text(value):
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def parse_decimal(value, field, errors, *, places="0.01", required=True):
    if value in (None, ""):
        if required:
            errors.append(f"{field} is required")
        return None
    try:
        return Decimal(str(value)).quantize(Decimal(places))
    except (InvalidOperation, ValueError):
        errors.append(f"{field} must be numeric")
        return None


def parse_datetime(value, field, errors, epoch, *, required=False):
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
            parsed = converted if isinstance(converted, datetime) else datetime.combine(converted, time.min)
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
        errors.append(f"{field} is not a valid date/time")
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def parse_date(value, field, errors, epoch, *, required=False):
    parsed = parse_datetime(value, field, errors, epoch, required=required)
    return parsed.date() if parsed else None
```

Then in `indents.py` delete the local `_text`, `_decimal`, `_datetime` and import `parse_text as _text`, `parse_datetime as _datetime`, plus define `def _decimal(value, field, errors): return parse_decimal(value, field, errors, places="0.001")` to keep the three-place quantisation. In `services.py` keep `_vendor_code` and any workbook helpers, but replace the bodies of `_text`, `_decimal`, `_date` with one-line calls to the shared functions (preserving each importer's `required`/`places` semantics exactly as they are today). `mis.py` keeps importing `_date`, `_decimal`, `_vendor_code` from `.services`.

- [ ] **Step 4: Run the suite**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass. If a legacy or indent test fails on an error message, the shared function changed wording; adjust the wrapper in that importer, not the test.

- [ ] **Step 5: Commit**

```bash
git add apps/api/imports/parsing.py apps/api/imports/services.py apps/api/imports/indents.py apps/api/imports/mis.py apps/api/tests/test_import_parsing.py
git commit -m "Share cell parsing between the three Excel importers"
```

---

### Task 8: Backend exposes enum choices for the frontend

**Files:**
- Modify: `apps/api/core/views.py` (add `ChoicesView`), `apps/api/config/urls.py` (route)
- Test: `apps/api/tests/test_review_fixes.py`

**Interfaces:**
- Produces: `GET /api/choices/` returning `{"trip_status": [{"value","label"}...], "document_kind": [...], "billing_status": [...], "payment_status": [...]}`. Task 9 consumes it.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_choices_endpoint_lists_backend_enums(users):
    response = client_for(users[User.Role.TRANSPORTER]).get("/api/choices/")
    assert response.status_code == 200
    values = [row["value"] for row in response.data["trip_status"]]
    assert "SETTLEMENT_APPROVAL_PENDING" in values
    assert {"value": "POD", "label": "POD"} in response.data["document_kind"] or any(r["value"] == "POD" for r in response.data["document_kind"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/api && .venv/Scripts/python -m pytest tests/test_review_fixes.py::test_choices_endpoint_lists_backend_enums -q -p no:cacheprovider`
Expected: FAIL with 404.

- [ ] **Step 3: Implement**

Add to `core/views.py`:

```python
class ChoicesView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        from operations.models import Document, Trip
        from payments.models import ClientBilling, FinancePaymentTransaction

        def rows(choices):
            return [{"value": value, "label": label} for value, label in choices]

        return Response(
            {
                "trip_status": rows(Trip.Status.choices),
                "document_kind": rows(Document.Kind.choices),
                "billing_status": rows(ClientBilling.Status.choices),
                "payment_status": rows(FinancePaymentTransaction.Status.choices),
            }
        )
```

Register in `config/urls.py` next to the settings route: `path("api/choices/", ChoicesView.as_view()),` and add `ChoicesView` to the `core.views` import.

- [ ] **Step 4: Run the suite and regenerate the schema check**

Run: `cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python manage.py spectacular --file schema.ci.yml --validate --fail-on-warn && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass, schema validates. Delete `schema.ci.yml` afterwards; it is a CI artifact.

- [ ] **Step 5: Commit**

```bash
git add apps/api/core/views.py apps/api/config/urls.py apps/api/tests/test_review_fixes.py
git commit -m "Expose backend enum choices for frontend filters"
```

---

### Task 9: Shared register filter hook, used by the TDS page

**Files:**
- Create: `apps/web/lib/useRegisterFilters.ts`
- Modify: `apps/web/app/tds/page.tsx`
- Test: `apps/web/e2e/finance-tds.spec.ts` (extend)

**Interfaces:**
- Produces: `useRegisterFilters<T extends Record<string, string>>(initial: T) -> { filters: T; set: (key: keyof T, value: string) => void; page: number; setPage: (n: number) => void; query: string }` where `query` is a URLSearchParams string including `page` and `page_size=25` and every non-empty filter.

- [ ] **Step 1: Write the failing e2e test**

Append to `apps/web/e2e/finance-tds.spec.ts` (copy the login helper already used in that file):

```ts
test("TDS register exposes vendor and date filters with pagination", async ({ page }) => {
  await loginAs(page, "finance");
  await page.goto("/tds");
  await expect(page.getByLabel("Transporter")).toBeVisible();
  await expect(page.getByLabel("From date")).toBeVisible();
  await page.getByLabel("From date").fill("2099-01-01");
  await expect(page.getByText("No posted TDS entries.")).toBeVisible();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx playwright test e2e/finance-tds.spec.ts -g "TDS register exposes"` (backend and web dev servers running as in CI)
Expected: FAIL, no "Transporter" label on the page.

- [ ] **Step 3: Implement the hook and the page**

```ts
// apps/web/lib/useRegisterFilters.ts
"use client";

import { useMemo, useState } from "react";

export function useRegisterFilters<T extends Record<string, string>>(initial: T, pageSize = 25) {
  const [filters, setFilters] = useState<T>(initial);
  const [page, setPage] = useState(1);
  const set = (key: keyof T, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setPage(1);
  };
  const query = useMemo(() => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    Object.entries(filters).forEach(([key, value]) => value && params.set(key, value));
    return params.toString();
  }, [filters, page, pageSize]);
  return { filters, set, page, setPage, pageSize, query };
}
```

Backend side: `TDSEntryViewSet.get_queryset` in `apps/api/payments/views.py:296` must accept `vendor`, `date_from`, `date_to`. Add after the transporter filter:

```python
        params = self.request.query_params
        if params.get("vendor"):
            queryset = queryset.filter(vendor_id=params["vendor"])
        if params.get("date_from"):
            queryset = queryset.filter(deduction_date__gte=params["date_from"])
        if params.get("date_to"):
            queryset = queryset.filter(deduction_date__lte=params["date_to"])
```

Rewrite `apps/web/app/tds/page.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import { useRegisterFilters } from "@/lib/useRegisterFilters";
import type { Paginated, Vendor } from "@/lib/types";
import { DateText, Empty, ErrorNotice, Loading, Money, PageHeader, Pagination, StatusBadge } from "@/components/UI";

type TDS = { id: number; deduction_date: string; vendor_name: string; trip_no: string; payment_no: string; taxable_base: string; rate: string; tds_amount: string; policy_snapshot: string; finance_reference: string; status: string };

export default function TDSRegisterPage() {
  const { filters, set, page, setPage, pageSize, query } = useRegisterFilters({ vendor: "", date_from: "", date_to: "" });
  const vendors = useQuery({ queryKey: ["vendors", "filter"], queryFn: () => api<Paginated<Vendor>>("/vendors/?page_size=200") });
  const entries = useQuery({ queryKey: ["tds", query], queryFn: () => api<Paginated<TDS>>(`/tds/?${query}`) });
  const rows = entries.data ? listResults(entries.data) : [];
  return <>
    <PageHeader title="TDS register" description="Transparent withholding by vendor, trip, payment, taxable base, rate and snapshotted policy." />
    <section className="panel"><div className="panel-body filters">
      <div className="field"><label htmlFor="tds-vendor">Transporter</label><select id="tds-vendor" className="input" value={filters.vendor} onChange={(e) => set("vendor", e.target.value)}><option value="">All transporters</option>{vendors.data && listResults(vendors.data).map((v) => <option key={v.id} value={v.id}>{v.display_name}</option>)}</select></div>
      <div className="field"><label htmlFor="tds-from">From date</label><input id="tds-from" className="input" type="date" value={filters.date_from} onChange={(e) => set("date_from", e.target.value)} /></div>
      <div className="field"><label htmlFor="tds-to">To date</label><input id="tds-to" className="input" type="date" value={filters.date_to} onChange={(e) => set("date_to", e.target.value)} /></div>
    </div></section>
    <section className="panel">
      {entries.isPending ? <Loading /> : entries.error ? <ErrorNotice error={entries.error} /> : rows.length === 0 ? <Empty message="No posted TDS entries." /> : <div className="table-wrap"><table>
        <thead><tr><th>Date</th><th>Vendor</th><th>Trip</th><th>Payment</th><th>Policy snapshot</th><th className="money">Taxable base</th><th className="money">Rate</th><th className="money">TDS</th><th>Status</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.id}><td><DateText value={row.deduction_date} /></td><td>{row.vendor_name}</td><td>{row.trip_no}</td><td>{row.payment_no}<div className="muted">{row.finance_reference}</div></td><td>{row.policy_snapshot.replaceAll("_", " ")}</td><td className="money"><Money value={row.taxable_base} /></td><td className="money">{row.rate}%</td><td className="money"><strong><Money value={row.tds_amount} /></strong></td><td><StatusBadge value={row.status} /></td></tr>)}</tbody>
      </table></div>}
      {entries.data && <Pagination count={entries.data.count} page={page} pageSize={pageSize} onPage={setPage} />}
    </section>
  </>;
}
```

- [ ] **Step 4: Verify**

Run: `cd apps/web && npm run lint && npm run typecheck && npm run build && npx playwright test e2e/finance-tds.spec.ts` and `cd apps/api && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/lib/useRegisterFilters.ts apps/web/app/tds/page.tsx apps/web/e2e/finance-tds.spec.ts apps/api/payments/views.py
git commit -m "Add register filter hook and filterable, paginated TDS register"
```

---

### Task 10: Vendor detail and fleet page stop fetching whole document tables

**Files:**
- Modify: `apps/web/app/vendors/[id]/page.tsx:172`, `apps/web/app/fleet/page.tsx:210-211,223,245`
- Create: `apps/web/components/DriverDocuments.tsx`

- [ ] **Step 1: Write the failing e2e assertion**

Append to `apps/web/e2e/smoke.spec.ts` inside the onboarding test (or a new test) after opening `/fleet`:

```ts
  const documentRequests: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/api/documents/")) documentRequests.push(request.url()); });
  await page.goto("/fleet");
  await expect(page.getByText("Driver master")).toBeVisible();
  expect(documentRequests.filter((url) => url.includes("page_size=500"))).toHaveLength(0);
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx playwright test e2e/smoke.spec.ts`
Expected: FAIL, one request with `page_size=500` is recorded.

- [ ] **Step 3: Implement**

```tsx
// apps/web/components/DriverDocuments.tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, listResults } from "@/lib/api";
import type { DocumentRecord, Paginated } from "@/lib/types";

export function DriverDocuments({ driverId }: { driverId: number }) {
  const [open, setOpen] = useState(false);
  const documents = useQuery({
    queryKey: ["documents", "driver", driverId],
    queryFn: async () => listResults(await api<Paginated<DocumentRecord>>(`/documents/?object_type=driver&object_id=${driverId}`)),
    enabled: open,
  });
  if (!open) return <button type="button" className="button small" onClick={() => setOpen(true)}>Show KYC</button>;
  if (documents.isPending) return <span className="muted">Loading…</span>;
  if (!documents.data?.length) return <span className="muted">Not uploaded</span>;
  return <>{documents.data.map((document) => <a key={document.id} className="chip" href={document.download_url}>{document.kind.replaceAll("_", " ")}</a>)}</>;
}
```

In `fleet/page.tsx`: remove the `documents:` entry from the `queryFn` object and the `driverDocs` helper, and replace the KYC cell body with `<DriverDocuments driverId={d.id} />`. Drop `DocumentRecord` from the type import if unused.

In `vendors/[id]/page.tsx` replace the `chequeProofs` query with one query per bank account inside the row render, using the same pattern:

```tsx
function ChequeProof({ bankId, uploaded }: { bankId: number; uploaded: boolean }) {
  const proof = useQuery({
    queryKey: ["documents", "vendor-bank-account", bankId],
    queryFn: async () => listResults(await api<Paginated<DocumentRecord>>(`/documents/?object_type=vendor_bank_account&object_id=${bankId}`))[0],
  });
  if (proof.data) return <a className="chip" href={proof.data.download_url}>View proof</a>;
  return <StatusBadge value={uploaded ? "VERIFIED" : "MISSING"} />;
}
```

and render `<ChequeProof bankId={bank.id} uploaded={bank.cancelled_cheque_uploaded} />` in the cheque column.

- [ ] **Step 4: Verify**

Run: `cd apps/web && npm run lint && npm run typecheck && npm run build && npx playwright test`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/DriverDocuments.tsx apps/web/app/fleet/page.tsx "apps/web/app/vendors/[id]/page.tsx" apps/web/e2e/smoke.spec.ts
git commit -m "Load driver and cheque documents on demand instead of whole tables"
```

---

### Task 11: Prettier formatting for the frontend

**Files:**
- Create: `apps/web/.prettierrc`, `apps/web/.prettierignore`
- Modify: `apps/web/package.json` (scripts, devDependencies), every `.ts`/`.tsx` under `apps/web/app`, `components`, `lib`, `e2e`

- [ ] **Step 1: Install and configure**

```bash
cd apps/web && npm install --save-dev prettier@3
```

`.prettierrc`:

```json
{ "printWidth": 120, "singleQuote": false, "trailingComma": "all" }
```

`.prettierignore`:

```
.next
node_modules
tsconfig.tsbuildinfo
```

Add scripts to `package.json`: `"format": "prettier --write ."` and `"format:check": "prettier --check ."`.

- [ ] **Step 2: Format and verify nothing else changed**

```bash
cd apps/web && npm run format && npm run lint && npm run typecheck && npm run build
```

Expected: only whitespace and line-break changes; lint, typecheck and build pass. Run `git diff --stat` and confirm no file outside `apps/web` changed.

- [ ] **Step 3: Add the check to CI**

In `.github/workflows/ci.yml`, in the `frontend` job after `npm run lint`, add:

```yaml
      - run: npm run format:check
        working-directory: apps/web
```

- [ ] **Step 4: Commit**

```bash
git add apps/web .github/workflows/ci.yml
git commit -m "Format the frontend with Prettier and enforce it in CI"
```

---

### Task 12: Trip register status filter reads choices from the backend

**Files:**
- Modify: `apps/web/app/trips/page.tsx` (status `<select>`), `apps/web/lib/types.ts` (add `Choice` type)

- [ ] **Step 1: Write the failing e2e assertion**

Append to `apps/web/e2e/smoke.spec.ts`:

```ts
test("trip register status filter lists every backend state", async ({ page }) => {
  await loginAs(page, "operations");
  await page.goto("/trips");
  const options = await page.locator("select[aria-label='Trip status'] option").allTextContents();
  expect(options).toContain("Settlement approval pending");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd apps/web && npx playwright test e2e/smoke.spec.ts -g "status filter"`
Expected: FAIL, the option is absent or the select has no aria-label.

- [ ] **Step 3: Implement**

Add to `lib/types.ts`: `export type Choice = { value: string; label: string };`.

In `trips/page.tsx` add a query `const choices = useQuery({ queryKey: ["choices"], queryFn: () => api<{ trip_status: Choice[] }>("/choices/"), staleTime: Infinity });` and replace the hard-coded status options with:

```tsx
<select aria-label="Trip status" className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
  <option value="">All statuses</option>
  {choices.data?.trip_status.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
</select>
```

Keep whatever state variable names the page already uses for `status` and `setPage`.

- [ ] **Step 4: Verify**

Run: `cd apps/web && npm run lint && npm run typecheck && npm run build && npx playwright test e2e/smoke.spec.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/trips/page.tsx apps/web/lib/types.ts apps/web/e2e/smoke.spec.ts
git commit -m "Drive the trip status filter from backend choices"
```

---

### Task 13: Browser test for the core trip to payment flow

**Files:**
- Create: `apps/web/e2e/core-flow.spec.ts`

- [ ] **Step 1: Write the test**

Reuse the `loginAs` helper pattern from `e2e/smoke.spec.ts`. Seeded demo users are `operations`, `approver`, `finance` with the password used in that helper.

```ts
import { expect, test } from "@playwright/test";
import { loginAs } from "./helpers";

test("operations builds an approval, approver approves, finance pays, ledger updates", async ({ page, request }) => {
  await loginAs(page, "operations");
  await page.goto("/approvals/new");
  const firstRow = page.locator("tbody tr").first();
  await expect(firstRow).toBeVisible();
  const tripNo = (await firstRow.locator("td").nth(1).innerText()).split("\n")[0].trim();
  await firstRow.locator("input[type=checkbox]").check();
  await page.getByRole("button", { name: "Create & submit approval" }).click();
  await expect(page).toHaveURL(/\/approvals\/\d+/);
  const approvalUrl = page.url();

  await loginAs(page, "approver");
  await page.goto(approvalUrl);
  await page.getByRole("button", { name: /Approve/ }).click();
  await expect(page.getByText("APPROVED").first()).toBeVisible();

  await loginAs(page, "finance");
  await page.goto("/finance");
  const line = page.locator("tr", { hasText: tripNo }).first();
  await line.locator("input[type=checkbox]").check();
  await page.getByLabel("UTR / bank reference").fill(`E2E-${Date.now()}`);
  await page.getByRole("button", { name: "Record paid transaction" }).click();
  await expect(page).toHaveURL(/\/payments\/\d+/);
  await expect(page.getByText("PAID").first()).toBeVisible();
});
```

If `e2e/helpers.ts` does not exist, move the existing `loginAs` function out of `smoke.spec.ts` into it and import it from both specs.

- [ ] **Step 2: Run it**

Run: `cd apps/web && npx playwright test e2e/core-flow.spec.ts` with a freshly seeded backend (`python manage.py migrate && python manage.py seed_demo`).
Expected: PASS. If the finance step fails because the vendor has no bank account in seed data, extend `seed_demo` to create one `VendorBankAccount` per demo vendor (look at `apps/api/core/management/commands/seed_demo.py:25-80` for how vendors are created) and rerun.

- [ ] **Step 3: Commit**

```bash
git add apps/web/e2e/core-flow.spec.ts apps/web/e2e/helpers.ts apps/web/e2e/smoke.spec.ts apps/api/core/management/commands/seed_demo.py
git commit -m "Add browser coverage for the trip approval and payment flow"
```

---

### Task 14: Environment example and deployment doc hygiene

**Files:**
- Modify: `.env.example`, `docs/deployment.md`

- [ ] **Step 1: Check for stale keys**

Run: `grep -n "GOOGLE\|GMAIL\|PUBSUB" .env.example docs/*.md`
Expected: any hit is stale; remove those lines.

- [ ] **Step 2: Document the encryption key**

In `.env.example`, above `FIELD_ENCRYPTION_KEY`, add:

```
# Mandatory in production (DJANGO_DEBUG=false). Generate once with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Losing or rotating it makes stored SMTP, WhatsApp, MFA and bank secrets unreadable.
```

In `docs/deployment.md`, add a "Secrets" paragraph stating the same, and that `python manage.py production_check` fails without it.

- [ ] **Step 3: Commit**

```bash
git add .env.example docs/deployment.md
git commit -m "Document the mandatory field encryption key and drop stale Gmail settings"
```

---

### Task 15: Open the pull request

- [ ] **Step 1: Full verification**

```bash
cd apps/api && .venv/Scripts/ruff check . && .venv/Scripts/python -m pytest -q -p no:cacheprovider -p no:warnings
cd ../web && npm run lint && npm run typecheck && npm run format:check && npm run build && npx playwright test
```

Expected: everything green.

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin fix/second-review
gh pr create --base main --title "Second review fixes: report queries, importer hardening, webhook scoping, register filters" --body-file docs/superpowers/plans/2026-09-06-second-review-fixes.md
```

Then edit the PR body down to a summary of the fifteen tasks plus the verification commands.
